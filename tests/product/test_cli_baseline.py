"""D173/T012: reference releases and later candidates; all command/help evidence is synthetic."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

from my_harness.adapters.cli_agents import SUPPORTED, VERSION, WRITE_SUPPORTED, CLIConfig, argv_for
from my_harness.adapters.cli_compatibility import CompatibilityError, MINIMUM
from my_harness.adapters.cli_diagnostics import ACCESS_REQUIRED, REQUIRED, preflight_config
from my_harness.services.local_config import load_local_config
import test_agent_roles
from test_agent_roles import journey, request, v2
from test_local_config import launches, setup, write  # noqa: F401 (fixture)
from test_typescript_profile import repository, web  # noqa: F401 (fixtures)

HELP = Path(__file__).parents[1] / 'fixtures' / 'cli_capabilities'
LATER = {'codex': '0.164.0', 'claude': '2.1.305'}
ROLES = ('planner', 'reviewer', 'phase', 'chat', 'bootstrap', 'definition', 'planning', 'executor')


def test_historical_lists_are_retained_as_evidence_and_not_exclusive_admission_lists():
    assert VERSION == 'cli-14'
    assert SUPPORTED == {'codex': ('0.161.0', '0.162.1', '0.163.0'),
                         'claude': ('2.1.295', '2.1.296', '2.1.304')}
    assert WRITE_SUPPORTED == {'codex': ('0.162.1', '0.163.0'), 'claude': SUPPORTED['claude']}
    assert MINIMUM == {'codex': '0.163.0', 'claude': '2.1.304'}


@pytest.mark.parametrize('provider,version', [('codex', '0.161.0'), ('codex', '0.162.2'),
                                              ('claude', '2.1.295'), ('claude', '2.1.303')])
@pytest.mark.parametrize('role', ['reviewer', 'executor'])
def test_below_minimum_is_readable_but_cannot_invoke(context, provider, version, role):
    config = CLIConfig(provider, ('/synthetic/cli',), version, (), 1)
    with pytest.raises(CompatibilityError, match='Update that client') as caught:
        argv_for(config, context, request(role))
    assert caught.value.code == 'minimum_version'


@pytest.mark.parametrize('role', ROLES)
@pytest.mark.parametrize('provider', ['codex', 'claude'])
def test_later_versions_preserve_the_reference_guard_argv(context, provider, role):
    tools = {'tools': ('Read', 'Edit'), 'allowed_tools': ('Read', 'Edit')} if provider == 'claude' else {}
    if role != 'executor':
        tools = {}
    reference = CLIConfig(provider, ('/synthetic/cli',), MINIMUM[provider], (), 1, **tools)
    assert argv_for(replace(reference, cli_version=LATER[provider]), context, request(role)) == argv_for(
        reference, context, request(role))


@pytest.mark.parametrize('provider', ['codex', 'claude'])
@pytest.mark.parametrize('version_kind', ['reference', 'later', 'major'])
def test_independently_authored_synthetic_help_and_auto_observation(tmp_path, provider, version_kind):
    version = MINIMUM[provider] if version_kind == 'reference' else LATER[provider] if version_kind == 'later' else '9.0.0'
    line = f'codex-cli {version}' if provider == 'codex' else f'{version} (Claude Code)'
    probe = tmp_path / 'probe.py'
    probe.write_text(f'''import sys
if sys.argv[1:] == ['--version']: print({line!r})
else: print({(HELP / f'{provider}-help.txt').read_text()!r})
''')
    config = CLIConfig(provider, (sys.executable, str(probe)), None, (), 5)
    for access in ('read', 'write'):
        report = preflight_config(config, access=access)
        assert report['available'] and report['observed_version'] == version, report
        assert report['requested_version'] is None
        assert report['compatibility']['classification'] == ('reference' if version_kind == 'reference' else 'candidate')
        assert report['compatibility']['internal_effects_verified'] is False
        assert report['missing_flags'] == []


@pytest.mark.parametrize('provider', ['codex', 'claude'])
def test_each_missing_flag_is_rejected_without_a_vendor_help_fixture(tmp_path, provider):
    original = (HELP / f'{provider}-help.txt').read_text()
    for flag in REQUIRED[provider] + ACCESS_REQUIRED.get((provider, 'read'), ()):
        probe = tmp_path / 'probe.py'
        line = f'codex-cli {MINIMUM[provider]}' if provider == 'codex' else f'{MINIMUM[provider]} (Claude Code)'
        changed = original.replace(flag, flag + '-other')
        probe.write_text(f'import sys\nprint({line!r} if "--version" in sys.argv else {changed!r})\n')
        report = preflight_config(CLIConfig(provider, (sys.executable, str(probe)), None, (), 5), access='read')
        assert report['available'] is False and flag in report['missing_flags'], (flag, report)


def test_announced_sandbox_choices_must_cover_the_requested_access(tmp_path):
    help_text = (HELP / 'codex-help.txt').read_text().replace('--sandbox', '--sandbox [possible values: read-only]')
    probe = tmp_path / 'probe.py'
    probe.write_text(f'import sys\nprint("codex-cli 0.164.0" if "--version" in sys.argv else {help_text!r})\n')
    config = CLIConfig('codex', (sys.executable, str(probe)), None, (), 5)
    assert preflight_config(config, access='read')['available']
    report = preflight_config(config, access='write')
    assert report['diagnostics'][0]['code'] == 'unsupported_values'
    assert report['unsupported_values'] == {'--sandbox': ['workspace-write']}


@pytest.mark.parametrize('reviewer,executor', test_agent_roles.PAIRS)
def test_four_pairings_admit_later_candidates_without_allowlist_changes(
        setup, repository, monkeypatch, reviewer, executor):
    for provider, version in LATER.items():
        monkeypatch.setitem(test_agent_roles.VERSIONS, provider, version)
    context, data, folder, tmp_path = setup
    config = load_local_config(write(folder, v2(data, reviewer, executor)))
    job, record = journey(repository, config, f'{reviewer}-{executor}-later')
    assert record.status == 'ACCEPTANCE_READY', record.history.stop
    specs = [row['spec'] for row in repository.processes(job.id)]
    assert [(s['provider'], s['cli_version']) for s in specs] == [
        (reviewer, LATER[reviewer]), (executor, LATER[executor]), (reviewer, LATER[reviewer])]
    assert all(s['preflight_observed']['compatibility']['classification'] == 'candidate' for s in specs)
    assert len(launches(tmp_path)) == 3


@pytest.fixture
def context(setup):
    return setup[0]
