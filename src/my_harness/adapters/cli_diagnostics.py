"""Bounded, explicit version/help probes shared with the CLI adapter.

Only trusted local executables belong here. This is not an OS sandbox.
Raw output, environment values and exception messages never enter the report.
"""
import hashlib
import json
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import tempfile
import time

from my_harness.i18n import tr
from my_harness.adapters.cli_compatibility import (CompatibilityError, MINIMUM, discover, eligible,
                                                      launch_identity, profile, version_tuple)


MAX_OUTPUT = 256 * 1024  # stdout and stderr combined, per command
TIMEOUT = 10.0
REQUIRED = {
    'codex': ('--json', '--model', '--sandbox', '--ephemeral', '--ignore-user-config',
              '--ignore-rules', '--strict-config', '--color', '--cd', '--config'),
    'claude': ('--print', '--output-format', '--verbose', '--include-partial-messages',
               '--no-session-persistence', '--session-id', '--model', '--effort',
               '--permission-mode', '--permission-prompts', '--tools', '--allowedTools',
               '--strict-mcp-config', '--mcp-config', '--setting-sources', '--settings',
               '--disable-slash-commands', '--no-chrome'),
}
# cli-5 (D052): flags needed only by one access mode of a provider.
ACCESS_REQUIRED = {('claude', 'read'): ('--restricted', '--json-schema'),
                   ('codex', 'read'): ('--skip-git-repo-check',)}
PATTERNS = {
    'codex': r'codex-cli ([0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6})',
    'claude': r'([0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}) \(Claude Code\)',
}
VALUES = {'codex': {'--color': ('never',)},
          'claude': {'--output-format': ('stream-json',), '--permission-mode': ('dontAsk',),
                     '--permission-prompts': ('none',)}}
# Only comma-separated values may continue onto another line. A bare word in a
# description is not a choice; closing delimiters and line ends bound each value.
_CHOICE_VALUE = (r'''(?:"[A-Za-z][A-Za-z0-9-]*"|'[A-Za-z][A-Za-z0-9-]*'|[A-Za-z][A-Za-z0-9-]*)'''
                 r'(?=[ \t]*(?:[,\)\]]|\r?$))')
_CHOICES = re.compile(rf'{_CHOICE_VALUE}(?:\s*,\s*{_CHOICE_VALUE})*', re.M)


def unsupported_values(text, provider, access):
    """Check explicitly advertised choices; an absent choices list is not a semantic observation."""
    required = dict(VALUES[provider])
    if provider == 'codex' and access is not None:
        required['--sandbox'] = ('workspace-write' if access == 'write' else 'read-only',)
    tokens = list(re.finditer(r'(?<![\w-])--[A-Za-z][A-Za-z0-9-]*(?![\w-])', text))
    missing = {}
    for index, token in enumerate(tokens):
        flag = token.group()
        if flag not in required:
            continue
        end = tokens[index + 1].start() if index + 1 < len(tokens) else len(text)
        section = text[token.end():end]
        announced = re.search(r'(?:possible values|choices)\s*:\s*', section, re.I)
        if announced:
            values = _CHOICES.match(section, announced.end())
            choices = set(re.findall(r'[A-Za-z][A-Za-z0-9-]*', values[0])) if values else set()
            absent = [value for value in required[flag] if value not in choices]
            if absent:
                missing[flag] = absent
    return missing


# Correction for each diagnostic code: catalog `cli_diagnostics.<code>`, in the emission's visual language.
FIXES = ('config_invalid', 'config_unreadable', 'spawn_error', 'timeout', 'output_limit', 'exit_error',
         'unexpected_output', 'version_mismatch', 'missing_flags', 'probe_error', 'cleanup_error',
         'minimum_version', 'client_missing', 'discovery_path', 'identity_changed', 'identity_unknown',
         'unresolved_client', 'guard_contract', 'unsupported_values')


def _probe(argv, environment, cwd, timeout):
    """Drain both pipes without unbounded buffering; kill our POSIX group on exit."""
    process = None
    output = bytearray()
    total = 0
    result = {'status': 'spawn_error', 'exit_code': None}
    try:
        process = subprocess.Popen(argv, env=dict(environment), cwd=cwd,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            for pipe in (process.stdout, process.stderr):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ)
            while selector.get_map() or process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    result['status'] = 'timeout'
                    break
                for key, _ in selector.select(min(remaining, 0.05)):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > MAX_OUTPUT:
                        result['status'] = 'output_limit'
                        break
                    if key.fileobj is process.stdout:
                        output.extend(chunk)
                if result['status'] == 'output_limit':
                    break
            else:
                result = {'status': 'ok' if process.returncode == 0 else 'exit_error',
                          'exit_code': process.returncode}
    except (OSError, ValueError):
        result['status'] = 'spawn_error' if process is None else 'probe_error'
    finally:
        if process is not None:
            # Also terminate children holding pipes after the leader has exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                result['status'] = 'cleanup_error'
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                result['status'] = 'cleanup_error'
            finally:
                process.stdout.close()
                process.stderr.close()
    return result, bytes(output) if result['status'] == 'ok' else b''


def preflight_config(config, *, timeout=TIMEOUT, access=None, expected_identity=None):
    """Observe one validated CLIConfig, without touching its frozen values.

    `access` ('read' | 'write') adds the flags that agent access mode needs.
    """
    if not math.isfinite(timeout) or not 0 < timeout <= TIMEOUT:
        raise ValueError(tr('cli_diagnostics.probe_timeout_positive_most'))
    if access not in (None, 'read', 'write'):
        raise ValueError(tr('cli_diagnostics.unknown_agent_access_mode'))
    required = REQUIRED[config.provider] + ACCESS_REQUIRED.get((config.provider, access), ())
    report = {'available': False, 'status': 'unknown', 'requested_version': config.cli_version,
              'observed_version': None, 'version_output': None, 'help_sha256': None,
              'required_flags': list(required),
              'missing_flags': None, 'probes': {}, 'diagnostics': [],
              'minimum_version': MINIMUM[config.provider], 'launch_sha256': None,
              'discovery': 'explicit' if config.executable else 'PATH', 'compatibility': None,
              'unsupported_values': {}}

    def fail(code, status='unknown', **params):
        report['status'] = status
        report['diagnostics'].append({'code': code, 'correction': tr(f'cli_diagnostics.{code}', **params)})
        return report

    try:
        try:
            config = discover(config)
            report['launch_sha256'] = launch_identity(config)[1]
        except CompatibilityError as exc:
            return fail(exc.code, **exc.params)
        except (FileNotFoundError, PermissionError, UnicodeError):
            report['probes']['version'] = {'status': 'spawn_error', 'exit_code': None}
            return fail('spawn_error')
        except (OSError, ValueError):
            return fail('identity_unknown')
        if expected_identity is not None and report['launch_sha256'] != expected_identity:
            return fail('identity_changed', 'incompatible')
        with tempfile.TemporaryDirectory(prefix='harness-preflight-') as cwd:
            version, raw = _probe(config.executable + ('--version',), config.environment, cwd, timeout)
            report['probes']['version'] = version
            if version['status'] != 'ok':
                return fail(version['status'])
            try:
                text = raw.decode('utf-8').strip()
            except UnicodeDecodeError:
                return fail('unexpected_output')
            match = re.fullmatch(PATTERNS[config.provider], text)
            if match is None or version_tuple(match[1]) is None:
                return fail('unexpected_output')
            report['observed_version'] = match[1]
            # Only the strict, recognized version line is safe to preserve.
            report['version_output'] = text
            if config.cli_version is not None and match[1] != config.cli_version:
                return fail('version_mismatch', 'incompatible')
            if not eligible(config.provider, match[1]):
                return fail('minimum_version', 'incompatible', provider=config.provider,
                            observed=match[1], minimum=MINIMUM[config.provider])
            args = ('exec', '--help') if config.provider == 'codex' else ('--help',)
            help_result, raw = _probe(config.executable + args, config.environment, cwd, timeout)
            report['probes']['help'] = help_result
            if help_result['status'] != 'ok':
                return fail(help_result['status'])
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                return fail('unexpected_output')
            if not text.strip() or '\0' in text:
                return fail('unexpected_output')
            report['help_sha256'] = hashlib.sha256(raw).hexdigest()
            # --model-extra must not satisfy --model.
            flags = set(re.findall(r'(?<![\w-])--[A-Za-z][A-Za-z0-9-]*(?![\w-])', text))
            if re.search(r'(?<![\w-])-c(?![\w-])', text):
                flags.add('--config')
            report['missing_flags'] = [flag for flag in required if flag not in flags]
            if report['missing_flags']:
                return fail('missing_flags', 'incompatible')
            report['unsupported_values'] = unsupported_values(text, config.provider, access)
            if report['unsupported_values']:
                return fail('unsupported_values', 'incompatible')
            if launch_identity(config)[1] != report['launch_sha256']:
                return fail('identity_changed', 'incompatible')
    except (OSError, ValueError):
        return fail('probe_error')
    report.update(available=True, status='version_help_match',
                  compatibility=profile(config.provider, report['observed_version'], access))
    return report


def diagnose(config):
    """CLIConfig syntax is checked by its constructor; semantic argv is untested."""
    from my_harness.adapters.cli_agents import SUPPORTED, VERSION
    return {'format': 1, 'provider': config.provider, 'adapter_version': VERSION,
            'historical_versions': SUPPORTED, 'minimum_versions': MINIMUM,
            'configuration': 'valid_structure', 'preflight': preflight_config(config),
            'not_checked': ['authentication', 'quota', 'model_access', 'full_argv',
                            'tool_permissions', 'network_isolation', 'cli_internal_retries'],
            'environment': 'explicit_without_inheritance'}


def diagnose_file(path):
    """Explicit data file only: never import managed factories or user modules."""
    from my_harness.adapters.cli_agents import CLIConfig, SUPPORTED

    def invalid(code):
        return {'format': 1, 'configuration': 'invalid', 'preflight': None,
                'historical_versions': SUPPORTED, 'minimum_versions': MINIMUM,
                'diagnostics': [{'code': code, 'correction': tr(f'cli_diagnostics.{code}')}]}

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate key')
            result[key] = value
        return result

    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536:
                return invalid('config_unreadable')
            raw = file.read(65537)
        if len(raw) > 65536:
            return invalid('config_unreadable')
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    except (OSError, ValueError, RecursionError):
        return invalid('config_unreadable')
    try:
        required = {'provider', 'environment', 'timeout_seconds'}
        optional = {'tools', 'allowed_tools', 'grantable_tools', 'executable', 'cli_version'}
        if not isinstance(data, dict) or not required <= data.keys() or data.keys() - required - optional:
            return invalid('config_invalid')
        for key in ('provider',):
            if not isinstance(data[key], str):
                return invalid('config_invalid')
        if 'cli_version' in data and not isinstance(data['cli_version'], str):
            return invalid('config_invalid')
        data.setdefault('cli_version', None)
        for key in ('executable', 'tools', 'allowed_tools', 'grantable_tools'):
            values = data.get(key, [])
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                return invalid('config_invalid')
            data[key] = tuple(values)
        env = data['environment']
        if not isinstance(env, dict) or not all(isinstance(value, str) for value in env.values()):
            return invalid('config_invalid')
        data['environment'] = tuple(env.items())
        if type(data['timeout_seconds']) not in (int, float):
            return invalid('config_invalid')
        config = CLIConfig(**data)
    except (ValueError, TypeError, OverflowError):
        return invalid('config_invalid')
    return diagnose(config)
