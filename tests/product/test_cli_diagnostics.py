"""H5.4: only synthetic executables, no installed CLI or user sessions."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys
import time

import pytest

from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter
from my_harness.adapters.cli_diagnostics import diagnose, diagnose_file, preflight_config, unsupported_values
from my_harness.cli import main


@pytest.fixture
def config(tmp_path):
    probe = tmp_path / 'probe.py'
    probe.write_text('''import json, os, sys, time, subprocess
from pathlib import Path
args = sys.argv[1:]
stage = 'version' if args == ['--version'] else 'help'
assert args in (['--version'], ['exec', '--help'], ['--help'])
assert sys.stdin.read() == ''
assert 'H5_SECRET_INHERITED' not in os.environ
assert Path.cwd() != Path(os.environ['CHECKOUT'])
with open(os.environ['RECORD'], 'a') as f:
    f.write(json.dumps(args) + '\\n')
mode = os.environ.get('MODE', '')
if stage == os.environ.get('STAGE', 'version'):
    if mode == 'timeout': time.sleep(60)
    if mode == 'closed_pipes':
        os.close(1); os.close(2); time.sleep(60)
    if mode == 'child':
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        Path(os.environ['CHILD']).write_text(str(child.pid))
        sys.exit(0)
    if mode == 'error':
        print('SECRET-OUTPUT', file=sys.stderr); sys.exit(7)
    if mode == 'flood':
        while True: os.write(1, b'x' * 8192)
    if mode == 'stderr_flood':
        while True: os.write(2, b'SECRET-OUTPUT' * 1024)
    if mode == 'invalid_utf8': os.write(1, b'\\xff'); sys.exit(0)
    if mode == 'unexpected': print('SECRET-OUTPUT'); sys.exit(0)
    if mode == 'empty': sys.exit(0)
    if mode == 'contaminated': print('codex-cli 0.163.0 SECRET-OUTPUT'); sys.exit(0)
    if mode == 'future': print('codex-cli 99.1.1'); sys.exit(0)
    if mode == 'suffix': print('codex-cli 0.163.0-beta'); sys.exit(0)
if stage == 'version':
    print('2.1.304 (Claude Code)' if os.environ['PROVIDER'] == 'claude' else 'codex-cli 0.163.0')
else:
    flags = '--json --model --sandbox --ephemeral --ignore-user-config --ignore-rules --strict-config --color --cd --config --skip-git-repo-check --print --output-format --verbose --include-partial-messages --no-session-persistence --session-id --effort --permission-mode --permission-prompts --tools --allowedTools --strict-mcp-config --mcp-config --setting-sources --settings --disable-slash-commands --no-chrome'
    if mode == 'missing': flags = flags.replace('--model', '--model-extra')
    if mode in ('wrapped_choices', 'excluded_choice'):
        flags += ' --restricted --json-schema'
        choice = 'dontAsk' if mode == 'wrapped_choices' else 'manual'
        flags = flags.replace('--permission-mode', '--permission-mode (choices: "manual",\\n    "' + choice + '")')
    print(flags)
    print('SECRET-OUTPUT', file=sys.stderr)
''')
    env = {'RECORD': str(tmp_path / 'record'), 'CHECKOUT': str(Path.cwd()),
           'PROVIDER': 'codex', 'CHILD': str(tmp_path / 'child')}
    return CLIConfig('codex', (sys.executable, str(probe)), '0.163.0', tuple(env.items()), 60)


def altered(config, **env):
    return replace(config, environment=tuple((dict(config.environment) | env).items()))


def calls(config):
    path = Path(dict(config.environment)['RECORD'])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
@pytest.mark.parametrize('quote', ['', '"', "'"])
@pytest.mark.parametrize('provider,flag,first,required,label,opening,closing', [
    ('claude', '--permission-mode', 'manual', 'dontAsk', 'choices', '(', ')'),
    ('codex', '--sandbox', 'read-only', 'workspace-write', 'possible values', '[', ']'),
])
def test_advertised_choices_preserve_values_on_continuation_lines(
        newline, quote, provider, flag, first, required, label, opening, closing):
    listing = f'{quote}{first}{quote},{newline}    {quote}{required}{quote}'
    text = f'{flag} <mode> {opening}{label}: {listing}{closing}{newline}--other-option'
    assert unsupported_values(text, provider, 'write') == {}
    assert unsupported_values(text.replace(newline, ' '), provider, 'write') == {}


@pytest.mark.parametrize('listing', [
    '(choices: "manual")\n    Example: dontAsk',
    'choices: manual\n    dontAsk appears in explanatory prose.',
    '(choices: manual,\n    explanation mentions dontAsk)',
    '(choices: manual) Extra text mentions dontAsk.',
    'choices: manual. An example mentions dontAsk.',
    '(choices: manual,\n    dontAsk-extra)',
    '(choices: manual,\n--another-option (choices: dontAsk)',
    '(choices: manual)\n--another-option (choices: dontAsk)',
])
def test_choice_lists_do_not_borrow_required_values_from_other_text(listing):
    assert unsupported_values('--permission-mode ' + listing, 'claude', 'read') == {
        '--permission-mode': ['dontAsk']}


def test_unwrapped_choice_list_stops_before_explanatory_prose():
    text = '--sandbox possible values: read-only,\n    workspace-write\n    Explanation: danger-full-access'
    assert unsupported_values(text, 'codex', 'write') == {}
    assert unsupported_values('--permission-mode No explicit list. Example: dontAsk', 'claude', 'read') == {}


@pytest.mark.parametrize('operation', ['preflight', 'diagnose'])
@pytest.mark.parametrize('mode,available', [('wrapped_choices', True), ('excluded_choice', False)])
def test_synthetic_client_with_wrapped_choices_is_diagnosed_without_inference(config, operation, mode, available):
    config = replace(altered(config, PROVIDER='claude', MODE=mode), provider='claude', cli_version='2.1.304')
    before = asdict(config)
    if operation == 'diagnose':
        result = diagnose(config)
        report = result['preflight']
    else:
        result = report = preflight_config(config, access='read')
    assert report['available'] is available
    assert report['status'] == ('version_help_match' if available else 'incompatible')
    assert report['missing_flags'] == []
    assert report['unsupported_values'] == ({} if available else {'--permission-mode': ['dontAsk']})
    if not available:
        assert report['diagnostics'][0]['code'] == 'unsupported_values'
    assert calls(config) == [['--version'], ['--help']]
    assert asdict(config) == before
    assert 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('provider', ['codex', 'claude'])
def test_success_exact_config_and_no_inheritance(config, provider, tmp_path, monkeypatch):
    monkeypatch.setenv('H5_SECRET_INHERITED', 'DO-NOT-PASS')
    config = replace(altered(config, PROVIDER=provider), provider=provider,
                     cli_version='0.163.0' if provider == 'codex' else '2.1.304')
    before = asdict(config)
    report = diagnose(config)
    assert report['preflight']['status'] == 'version_help_match'
    assert report['preflight']['observed_version'] == config.cli_version
    assert report['preflight']['missing_flags'] == []
    assert len(report['preflight']['help_sha256']) == 64
    assert report['configuration'] == 'valid_structure'
    assert {'authentication', 'quota', 'full_argv'} <= set(report['not_checked'])
    assert asdict(config) == before
    assert calls(config) == [['--version'], ['exec', '--help'] if provider == 'codex' else ['--help']]
    assert 'SECRET' not in json.dumps(report)
    assert str(tmp_path) not in json.dumps(report)


@pytest.mark.parametrize('stage', ['version', 'help'])
@pytest.mark.parametrize('mode,code', [
    ('timeout', 'timeout'), ('closed_pipes', 'timeout'), ('child', 'timeout'),
    ('error', 'exit_error'), ('flood', 'output_limit'), ('stderr_flood', 'output_limit'),
    ('invalid_utf8', 'unexpected_output'), ('empty', 'unexpected_output'),
])
def test_bounded_failures_no_retry(config, stage, mode, code):
    config = altered(config, STAGE=stage, MODE=mode)
    started = time.monotonic()
    report = preflight_config(config, timeout=0.3)
    assert time.monotonic() - started < 3
    assert report['available'] is False and report['status'] == 'unknown'
    assert report['diagnostics'][0]['code'] == code
    assert report['diagnostics'][0]['correction']
    assert len(calls(config)) == (1 if stage == 'version' else 2)
    assert 'SECRET' not in json.dumps(report)
    if mode == 'error':
        assert report['probes'][stage]['exit_code'] == 7
    if mode == 'child':
        # A surviving pipe writer would leave the probe blocked until 60s.
        child = int(Path(dict(config.environment)['CHILD']).read_text())
        # A zombie is dead but may briefly await the system reaper.
        import subprocess
        state = subprocess.run(['/bin/ps', '-p', str(child), '-o', 'stat='], capture_output=True)
        assert not state.stdout.strip() or state.stdout.strip().startswith(b'Z')


@pytest.mark.parametrize('mode', ['unexpected', 'contaminated', 'suffix'])
def test_unrecognized_version_not_compatible(config, mode):
    report = preflight_config(altered(config, MODE=mode))
    assert report['observed_version'] is None
    assert report['version_output'] is None
    assert report['diagnostics'][0]['code'] == 'unexpected_output'
    assert len(calls(config)) == 1


def test_version_mismatch_no_help_or_substitution(config):
    report = preflight_config(altered(config, MODE='future'))
    assert report['status'] == 'incompatible'
    assert report['requested_version'] == '0.163.0'
    assert report['observed_version'] == '99.1.1'
    assert report['missing_flags'] is None
    assert len(calls(config)) == 1


def test_flag_prefix_is_not_capability(config):
    report = preflight_config(altered(config, MODE='missing', STAGE='help'))
    assert report['status'] == 'incompatible'
    assert report['missing_flags'] == ['--model']


def test_unavailable_executable_sanitized(config, tmp_path):
    report = preflight_config(replace(config, executable=(str(tmp_path / 'SECRET-PATH'),)))
    assert report['diagnostics'][0]['code'] == 'spawn_error'
    assert report['probes']['version']['exit_code'] is None
    assert 'SECRET' not in json.dumps(report)


def test_shared_adapter_preflight_no_mutation(config, tmp_path):
    claude = replace(altered(config, PROVIDER='claude'), provider='claude', cli_version='2.1.304')
    adapter = CLIProcessAdapter([config, claude], tmp_path / 'captures')
    before = adapter.frozen_versions()
    report = adapter.preflight()
    assert all(item['available'] for item in report.values())
    assert adapter.frozen_versions() == before
    assert adapter.journal is None and adapter.availability is None
    assert not adapter.artifact_root.exists()


def data_for(config):
    data = asdict(config)
    data['environment'] = dict(config.environment)
    return data


@pytest.mark.parametrize('field,value', [
    ('provider', 'SECRET'), ('cli_version', '99.1.1-beta'), ('executable', ['relative']),
    ('executable', 'SECRET'), ('environment', {'KEY': 1}), ('environment', []),
    ('timeout_seconds', 0), ('timeout_seconds', float('nan')), ('timeout_seconds', True),
    ('tools', ['--bad']), ('extra', 'SECRET'), ('cli_version', []),
])
def test_invalid_configuration_stops_before_process(config, tmp_path, field, value):
    path = tmp_path / 'config.json'
    data = data_for(config)
    data[field] = value
    path.write_text(json.dumps(data))
    report = diagnose_file(path)
    assert report['configuration'] == 'invalid' and report['preflight'] is None
    assert report['diagnostics'][0]['code'] == 'config_invalid'
    assert calls(config) == []
    assert 'SECRET' not in json.dumps(report)


@pytest.mark.parametrize('kind', ['missing', 'directory', 'symlink', 'hardlink', 'fifo',
                                 'large', 'invalid_json', 'duplicate', 'invalid_utf8', 'deep'])
def test_unreadable_config_is_bounded(config, tmp_path, kind):
    path = tmp_path / 'config.json'
    if kind == 'directory': path.mkdir()
    elif kind == 'symlink': path.symlink_to(Path(config.executable[1]))
    elif kind == 'hardlink': os.link(config.executable[1], path)
    elif kind == 'fifo': os.mkfifo(path)
    elif kind == 'large': path.write_bytes(b'x' * 65537)
    elif kind == 'invalid_json': path.write_text('SECRET')
    elif kind == 'duplicate': path.write_text('{"provider":"codex","provider":"claude"}')
    elif kind == 'invalid_utf8': path.write_bytes(b'\xff')
    elif kind == 'deep': path.write_text('[' * 2000 + ']' * 2000)
    report = diagnose_file(path)
    # Python/pytest recursion limits decide whether parsing or shape rejects it.
    expected = {'config_unreadable', 'config_invalid'} if kind == 'deep' else {'config_unreadable'}
    assert report['diagnostics'][0]['code'] in expected
    assert calls(config) == []


def test_cli_json_and_exit_codes_without_database(config, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('HARNESS_DATABASE_URL', 'invalid://must-not-open')
    monkeypatch.setenv('HARNESS_MANAGED_CONFIG', 'must_not_import:factory')
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(data_for(config)))
    before = path.read_bytes()
    assert main(['diagnose-cli', str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['preflight']['available']
    assert path.read_bytes() == before
    assert main(['diagnose-cli', str(tmp_path / 'missing')]) == 1
    assert json.loads(capsys.readouterr().out)['preflight'] is None
    path.write_text(json.dumps(data_for(altered(config, MODE='future'))))
    assert main(['diagnose-cli', str(path)]) == 1
    assert json.loads(capsys.readouterr().out)['preflight']['status'] == 'incompatible'


def test_unencodable_executable_is_a_diagnostic(config):
    report = preflight_config(replace(config, executable=('/SECRET-\ud800',)))
    assert report['diagnostics'][0]['code'] == 'spawn_error'
    assert 'SECRET' not in json.dumps(report)


def test_environment_values_not_reported(config, tmp_path):
    config = altered(config, API_KEY='SECRET-CREDENTIAL', HOME=str(tmp_path / 'SECRET-HOME'))
    result = diagnose(config)
    assert result['preflight']['available']
    assert 'SECRET' not in json.dumps(result)
    assert not (tmp_path / 'SECRET-HOME').exists()


def test_probe_setup_failure_is_sanitized(config, monkeypatch):
    import my_harness.adapters.cli_diagnostics as module
    def denied(**kwargs):
        raise PermissionError('SECRET-PATH')
    monkeypatch.setattr(module.tempfile, 'TemporaryDirectory', denied)
    result = preflight_config(config)
    assert result['diagnostics'][0]['code'] == 'probe_error'
    assert calls(config) == []
    assert 'SECRET' not in json.dumps(result)


def test_uncertain_cleanup_never_certifies_success(config, monkeypatch):
    import my_harness.adapters.cli_diagnostics as module
    def denied(*args):
        raise PermissionError('SECRET-PROCESS')
    monkeypatch.setattr(module.os, 'killpg', denied)
    result = preflight_config(config)
    assert result['available'] is False
    assert result['diagnostics'][0]['code'] == 'cleanup_error'
    assert len(calls(config)) == 1
    assert 'SECRET' not in json.dumps(result)
