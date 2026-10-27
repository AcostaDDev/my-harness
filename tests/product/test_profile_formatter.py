"""P009-T019 (D133): the profile formatter lets a shell-less executor meet the format check of the profile.

T009 stopped at the revision limit: the Claude executor (Read/Edit/Write/Glob/Grep, D121) cannot run Ruff, formatted
by hand to another width, and `ruff format --check .` only names the file. Offline: scripted agents and a synthetic
formatter; the native runner only launches the test's Python.
"""
from dataclasses import asdict, replace
import hashlib
import json
import sys

import pytest

from my_harness.adapters.commands import CommandConfig, ManagedCommandRunner, config_payload
from my_harness.core.engine.context import Command, ProjectProfile
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.serialization import dump_history, load_history
from my_harness.core.engine.validation import CommandResult, run_command
from my_harness.recipes import django
from my_harness.services.local_config import LocalConfigError, _commands, load_local_config
from test_commands import setup as native
from test_engine import PHASE_ID, PLAN, TASK_ID, context, harness, review  # noqa: F401 (fixture)
from test_local_config import setup, web, write  # noqa: F401
from test_managed import repository  # noqa: F401
from test_project_preparation import recipe_data
from test_project_registry import operator  # noqa: F401

FORMATTER = ('fmt', '--')
CHECK = Command(('fmt', '--check', '.'))
UNFORMATTED, FORMATTED = "VALUE = 'x'\n", 'VALUE = "x"\n'
# The recipe fingerprint binds the preparation receipts already issued, among them the pilot child's (D119, D130).
RECIPE_FINGERPRINT = 'd2b89bcaa647d659dac7417c4af53e7cb532cfbaef1fd7346cb29d440eb35ff2'


def formatting_profile(context, **changes):
    profile = replace(context.profile, validations=(CHECK,), allowed_command_prefixes=(('fmt',),),
                      formatter_argv=FORMATTER, formatter_paths=('*.py',))
    return replace(context, profile=replace(profile, **changes))


def by_hand(files):
    """Shell-less executor: writes files, never runs a tool."""
    def response(context, request):
        for path, text in files.items():
            if text is None:
                context.path(path).unlink()
            else:
                context.path(path).parent.mkdir(parents=True, exist_ok=True)
                context.path(path).write_text(text)
        return {'result': 'Edited by hand; no shell to run the formatter'}
    return response


def tool(calls):
    """Synthetic formatter and check: one rule, single to double quotes, like `ruff format`."""
    def run(context, command):
        calls.append(command.argv)
        if command.argv[:2] == FORMATTER:
            for path in command.argv[2:]:
                context.path(path).write_text(context.path(path).read_text().replace("'", '"'))
            return CommandResult(0, f'{len(command.argv) - 2} file(s) reformatted')
        pending = [p for p in ('app/main.py', 'app/other.py') if context.path(p).exists()
                   and "'" in context.path(p).read_text()]
        return CommandResult(1 if pending else 0, ''.join(f'Would reformat: {p}\n' for p in pending))
    return run


def revise():
    finding = {'severity': 'medium', 'category': 'validation', 'file': 'app/main.py', 'problem': 'would be reformatted'}
    return review('REVISE', findings=[finding])


def reviewer_input(agents):
    return json.loads(json.loads(agents.requests[-1].prompt_snapshot_json)['parts'][0]['variables']['INPUT_JSON'])


def test_t009_without_a_formatter_spends_every_revision_on_a_format_the_executor_cannot_see(context):
    """Characterization of D132: the same finding and the same failed check until the revision limit."""
    context = formatting_profile(context, formatter_argv=(), formatter_paths=())
    calls = []
    # The second turn reformats by hand to another style and the check still fails, as in T009.
    engine, agents, _, _ = harness(context, [by_hand({'app/main.py': UNFORMATTED}), revise(),
                                             by_hand({'app/main.py': "VALUE = 'x'  # by hand\n"}), revise()],
                                   [tool(calls)] * 2, paths=('app/main.py',))
    result = engine.start(replace(context, policy=replace(context.policy, max_revision_cycles=1)), TASK_ID, PHASE_ID,
                          PLAN.replace('`app/**`', '`app/`').replace('`test-runner check`', '`fmt --check .`'))
    assert result.status == 'revision_limit'
    assert [cycle.validation.all_passed for cycle in result.cycles] == [False, False]
    assert all(cycle.formatting_json is None for cycle in result.cycles) and calls == [CHECK.argv] * 2


def test_t009_with_the_profile_formatter_reaches_acceptance_in_the_first_review(context):
    context = formatting_profile(context)
    calls = []
    engine, agents, _, _ = harness(context, [by_hand({'app/main.py': UNFORMATTED}), review()], [tool(calls)] * 2,
                                   paths=('app/main.py',))
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN.replace('`test-runner check`', '`fmt --check .`'))
    assert result.status == 'acceptance_ready' and result.acceptance.eligible
    assert [a.request.role for a in result.attempts] == ['executor', 'reviewer']
    assert calls == [('fmt', '--', 'app/main.py'), CHECK.argv]
    assert context.path('app/main.py').read_text() == FORMATTED
    (cycle,) = result.cycles
    record = json.loads(cycle.formatting_json)
    assert record['paths'] == ['app/main.py'] and record['result']['exit_code'] == 0
    assert record['command'] == {'argv': ['fmt', '--', 'app/main.py'], 'cwd': '.', 'environment': [],
                                 'timeout_seconds': 120}
    assert reviewer_input(agents)['formatting'] == record
    assert cycle.evidence == result.acceptance.evidence  # acceptance binds the formatted bytes
    instructions = json.loads(agents.requests[0].prompt_snapshot_json)['parts'][0]['variables']['PROFILE_INSTRUCTIONS']
    assert '`fmt --`' in instructions and '*.py' in instructions
    assert load_history(dump_history(result)) == result
    assert json.loads(dump_history(result))['format'] == 8


def test_only_contract_files_the_formatter_declares_are_formatted_after_each_executor_turn(context):
    context = formatting_profile(context, protected_paths=('app/protected.py',))
    for path in ('app/gone.py', 'app/protected.py'):
        context.path(path).write_text(UNFORMATTED)
    calls = []
    files = {'app/main.py': UNFORMATTED, 'app/notes.txt': "'x'", 'app/protected.py': None, 'app/gone.py': None}
    engine, _, _, _ = harness(context, [by_hand(files), revise(), by_hand({'app/other.py': UNFORMATTED}), review()],
                              [tool(calls)] * 4, paths=('app/main.py', 'app/other.py', 'app/notes.txt',
                                                        'app/protected.py', 'app/gone.py'))
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN.replace('`test-runner check`', '`fmt --check .`'))
    # Deleted, protected and non-matching paths are never formatter arguments; each turn formats again.
    assert calls == [('fmt', '--', 'app/main.py'), CHECK.argv, ('fmt', '--', 'app/main.py', 'app/other.py'),
                     CHECK.argv]
    assert result.stop.stage == 'acceptance'  # the protected deletion still fails the path policy
    assert context.path('app/notes.txt').read_text() == "'x'"


def test_revalidation_and_tasks_without_matching_files_keep_the_previous_flow(context):
    context = formatting_profile(context)
    calls = []
    engine, agents, _, _ = harness(context, [by_hand({'app/main.txt': 'implemented'}), review('BLOCKED')],
                                   [tool(calls)] * 3, paths=('app/main.txt', 'app/main.py'))
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN.replace('`test-runner check`', '`fmt --check .`'))
    assert result.status == 'blocked' and calls == [CHECK.argv]
    assert result.cycles[0].formatting_json is None and 'formatting' not in reviewer_input(agents)
    dumped = json.loads(dump_history(result))
    assert dumped['format'] < 8 and 'formatting_json' not in dumped['history']['cycles'][0]
    # Revalidating never runs the formatter: no executor turn produced the change (a person may have edited it).
    context.path('app/main.py').write_text(UNFORMATTED)
    agents.responses.append(review('BLOCKED'))
    resumed = engine.resume(context, result)
    assert resumed.status == 'blocked' and calls == [CHECK.argv] * 2
    assert context.path('app/main.py').read_text() == UNFORMATTED and resumed.cycles[-1].formatting_json is None


def test_a_formatter_that_does_not_run_stops_before_review_and_an_exit_code_reaches_the_reviewer(context):
    context = formatting_profile(context)
    engine, agents, _, _ = harness(context, [by_hand({'app/main.py': UNFORMATTED})],
                                   [CommandResult(None, error='Configured executable unavailable or not executable')],
                                   paths=('app/main.py',))
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN)
    assert result.status == 'stopped' and result.stop.stage == 'formatter' and 'unavailable' in result.stop.reason
    assert [a.request.role for a in result.attempts] == ['executor'] and result.cycles == ()
    engine, agents, _, _ = harness(context, [by_hand({'app/main.py': 'VALUE = (\n'}), review('BLOCKED')],
                                   [CommandResult(2, stderr='error: Failed to parse app/main.py')],
                                   paths=('app/main.py',))
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN)
    assert result.status == 'blocked'
    assert reviewer_input(agents)['formatting']['result']['exit_code'] == 2


def test_profile_rejects_a_formatter_whose_paths_could_become_options():
    with pytest.raises(ValueError, match='formatter'):
        ProjectProfile('p', formatter_argv=('fmt',), formatter_paths=('*.py',))
    with pytest.raises(ValueError, match='formatter'):
        ProjectProfile('p', formatter_argv=('fmt', '--'))


def configuration(context, **changes):
    return CommandConfig(str(context.root), True, (Command(('python', '-c', 'pass')),), (('python', sys.executable),),
                         (), **changes)


def test_native_runner_authorizes_the_formatter_only_on_existing_checkout_files(repository, context):
    script = "import pathlib, sys; [pathlib.Path(p).write_text('formatted') for p in sys.argv[2:]]"
    context.path('app/main.py').write_text(UNFORMATTED)
    config = configuration(context, formatter_argv=('python', '-c', script, '--'))
    port, journal, job, claim = native(repository, context, config)
    try:
        result = run_command(context, port, Command(('python', '-c', script, '--', 'app/main.py')), journal)
        assert result.passed and context.path('app/main.py').read_text() == 'formatted'
        (process,) = repository.command_processes(job.id)
        assert process['spec']['authorization'] == 'formatter-paths'
        context.path('app/link.py').symlink_to(context.path('app/main.py'))
        for argv, cwd, environment in [(('app/missing.py',), '.', ()), (('app/link.py',), '.', ()),
                                       (('../outside.py',), '.', ()), (('-x',), '.', ()), (('app',), '.', ()),
                                       ((), '.', ()), (('app/main.py',), 'app', ()),
                                       (('app/main.py',), '.', (('EXTRA', '1'),))]:
            command = Command(('python', '-c', script, '--', *argv), cwd, environment) if argv else Command(
                ('python', '-c', script, '--'))
            assert run_command(context, port, command, journal).error
        assert run_command(context, port, Command(('python', '-c', 'pass', '--', 'app/main.py')), journal).error
        assert len(repository.command_processes(job.id)) == 1
    finally:
        repository.close_owner(claim)


def test_native_configuration_hash_without_a_formatter_is_the_one_frozen_before(context):
    config = configuration(context)
    old = {key: value for key, value in asdict(config).items() if key != 'formatter_argv'}
    assert config_payload(config) == old
    assert ManagedCommandRunner(config).frozen_versions()['command_config_sha256'] == hashlib.sha256(
        freeze(old).encode()).hexdigest()
    formatting = ManagedCommandRunner(configuration(context, formatter_argv=('python', '--')))
    assert formatting.frozen_versions() != ManagedCommandRunner(config).frozen_versions()
    for argv in (('python',), ('missing', '--')):
        with pytest.raises(ValueError, match='Formatter'):
            configuration(context, formatter_argv=argv)


def test_recipe_profile_declares_the_formatter_outside_the_recipe_fingerprint(operator):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, recipe_data(data, folder)))
    profile = config.registrar.profiles['python-django-recipe']
    assert (profile.formatter_argv, profile.formatter_paths) == (('ruff', 'format', '--'), ('*.py',))
    assert replace(profile, formatter_argv=(), formatter_paths=()) == django.profile()
    assert django.fingerprint() == RECIPE_FINGERPRINT
    # Variable paths never fit an exact authorization, so a formatter requires the profile's own authorization.
    table = {'executables': {'fmt': sys.executable}, 'environment': {}, 'authorize_profile_commands': False}
    with pytest.raises(LocalConfigError, match='formatter'):
        _commands(table, 'compositions.x', tmp_path, ProjectProfile('p', formatter_argv=FORMATTER,
                                                                    formatter_paths=('*.py',)))
    assert _commands({**table, 'authorize_profile_commands': True}, 'compositions.x', tmp_path, ProjectProfile(
        'p', formatter_argv=FORMATTER, formatter_paths=('*.py',))).formatter_argv == FORMATTER
