"""Operator TOML outside managed checkouts → explicit ManagedConfig (`local-config-8`).

`local-config-8` adds an optional formatter argv/path pair to declared profiles, using the existing engine and
native runner authorization. Formats 1–7 retain their declaration rules and frozen hashes.
`local-config-7` (P011-T012, D174) makes executable and version optional: selected clients are resolved
on the explicit PATH in a separate admission step; loading remains data-only. Formats 1–6 keep their hashes.
`local-config-6` (P011-T008, D167) is `local-config-5` plus an optional `[[projects]].work_language` (en/es):
the service records it once for the project's root at startup and SQLite rules afterwards; another value for an
associated root stops the service. Its `[recipes]` select the packaged v2 recipes (P011-T020, D168), which
prepare with the project's work language; the same keys in `local-config-5` keep selecting v1.
`local-config-5` (P009-T003) adds private role presets and optional project selections, and
optional packaged recipes: `[recipes.django]` (D119) and `[recipes.typescript-web]` (D142).
Effective agents are composed per checkout; older formats keep their frozen identity.
`local-config-4` (P008-T008) is `local-config-3` plus optional `[profiles.NAME]`:
stack profiles declared by the operator (preparation, validations with JUnit,
command prefixes, protected/sensitive paths, data-model paths and executor
instructions) that compositions name like a built-in one. Commands are argv
without shell; the profile content enters the frozen composition hash.
`local-config-3` (D076) keeps the `local-config-2` agents and groups the profile
commands in named `[compositions.NAME]`; `[registration]` lists the canonical
roots under which the UI may register projects (SQLite, D054) and whether those
may enable bootstrap. `[[projects]]` is optional and names a composition.
`local-config-2` (D052) declares `[agents.reviewer]` and `[agents.executor]`,
each Codex or Claude. `local-config-1` is still read as Codex reviewer and
Claude executor with its own policy (separate planner selection). Neither of
them can register projects from the UI.

Loading never launches processes or reads managed repositories. Trust,
environment, models and command authorizations come only from
this file; v7/v8 may discover the selected executable on that explicit environment's PATH. Provider authentication
stays with each installed CLI: the file must not contain secrets.
"""
from dataclasses import asdict, replace
import hashlib
import importlib.metadata
import math
import os
from pathlib import Path
import pwd
import re
import stat
from threading import Lock
import tomllib

from my_harness.adapters.cli_agents import EFFORTS, CLIConfig, CLIProcessAdapter
from my_harness.adapters.cli_compatibility import CompatibilityError, discover, launch_identity
from my_harness.adapters.cli_diagnostics import preflight_config
from my_harness.adapters.commands import CommandConfig, ManagedCommandRunner, config_payload
from my_harness.adapters.git import GitWorkspace
from my_harness.core.engine.commit import GitIdentity
from my_harness.core.engine.context import (Command, EnginePolicy, JUnitDeclaration, ProjectContext,
                                               ProjectProfile, relative_path)
from my_harness.core.engine.contracts import MODEL_FORM, freeze
from my_harness.core.engine.documents import DOCUMENT_LAYOUT
from my_harness.core.engine.journal import JournalError
from my_harness.i18n import LANGUAGES, tr
from my_harness.profiles.typescript_web import typescript_web_profile
from my_harness.recipes import RECIPES, by_version as recipe_version, implementation, module as recipe_module
from my_harness.services.managed_runtime import (PROJECT_ID, ManagedConfig, ManagedProject, agents_view,
                                                    validate_projects)

EDITOR_VERSION = 'local-config-9'
VERSION = 'local-config-8'
V7 = 'local-config-7'
V6 = 'local-config-6'
V5 = 'local-config-5'
FORMATS = ('local-config-1', 'local-config-2', 'local-config-3', 'local-config-4', V5, V6, V7, VERSION)
REGISTRABLE = ('local-config-3', 'local-config-4', V5, V6, V7, VERSION, EDITOR_VERSION)
PROFILE_FORMATS = ('local-config-4', V5, V6, V7, VERSION, EDITOR_VERSION)
# v5 adds presets/selections and recipes; v6 keeps the presets/selections and adds the work language.
AGENT_FORMATS = (V5, V6, V7, VERSION, EDITOR_VERSION)
WORK_FORMATS = (V6, V7, VERSION, EDITOR_VERSION)
AUTOMATIC_FORMATS = (V7, VERSION, EDITOR_VERSION)
CLI_KEYS = ('executable', 'cli_version', 'timeout_seconds', 'environment')
TOOL_KEYS = ('tools', 'allowed_tools', 'grantable_tools')
CONFIG_ENV = 'HARNESS_LOCAL_CONFIG'
MAX_BYTES = 65536
PROFILES = {'typescript-web': typescript_web_profile}
PROFILE_KEYS = ('preparation', 'validations', 'allowed_command_prefixes', 'protected_paths', 'sensitive_paths',
                'data_model_paths', 'executor_instructions')
# argv without shell: the executable is a name from `executables`, never a command interpreter, and no argument
# carries syntax that only a shell would interpret (the runner does not interpret it and its presence reveals an error).
COMMAND_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,63}')
SHELLS = frozenset({'sh', 'bash', 'zsh', 'dash', 'ksh', 'mksh', 'ash', 'fish', 'csh', 'tcsh', 'busybox'})
SHELL_TOKENS = frozenset({';', '&', '&&', '|', '||', '|&', '>', '>>', '<', '<<', '2>', '2>&1'})


class LocalConfigError(ValueError):
    pass


def _fields(value, where, required, optional=()):
    if not isinstance(value, dict):
        raise LocalConfigError(tr('config.table_expected', where=where))
    unknown = set(value) - set(required) - set(optional)
    missing = set(required) - set(value)
    if unknown or missing:
        raise LocalConfigError(tr('config.keys', where=where, unknown=sorted(unknown), missing=sorted(missing)))
    return value


def _text(value, where):
    if not isinstance(value, str) or not value.strip() or '\0' in value:
        raise LocalConfigError(tr('config.text_required', where=where))
    return value


def _flag(value, where):
    if type(value) is not bool:
        raise LocalConfigError(tr('config.boolean_required', where=where))
    return value


def _number(value, where):
    if type(value) not in (int, float) or not math.isfinite(value) or not value > 0:
        raise LocalConfigError(tr('config.number_required', where=where))
    return value


def _texts(value, where, *, empty=False):
    if not isinstance(value, list) or (not value and not empty):
        raise LocalConfigError(tr('config.texts_required', where=where))
    return tuple(_text(item, where) for item in value)


def _path(value, where, *, kind):
    path = Path(_text(value, where))
    if not path.is_absolute() or path.resolve() != path:
        raise LocalConfigError(tr('config.path_required', where=where))
    if kind == 'directory' and not path.is_dir():
        raise LocalConfigError(tr('config.directory_required', where=where))
    if kind == 'executable' and not (path.is_file() and os.access(path, os.X_OK)):
        raise LocalConfigError(tr('config.executable_required', where=where))
    return path


def _executable(value, where):
    """Only the command itself is checked here; operators may name versioned symlinks."""
    path = Path(_text(value, where))
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise LocalConfigError(tr('config.absolute_executable', where=where))
    return str(path)


def _environment(value, where):
    if not isinstance(value, dict) or any(not isinstance(v, str) or '\0' in v for v in value.values()):
        raise LocalConfigError(tr('config.environment_required', where=where))
    return tuple(sorted((_text(key, where), item) for key, item in value.items()))


def _read(path):
    if not path.is_absolute() or path.resolve() != path:
        raise LocalConfigError(tr('config.file_path'))
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise LocalConfigError(tr('config.unreadable', reason=exc.strerror)) from None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
            raise LocalConfigError(tr('config.file_kind'))
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise LocalConfigError(tr('config.file_owner'))
        raw = stream.read(MAX_BYTES + 1)
    try:
        return tomllib.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise LocalConfigError(tr('config.toml_invalid', error=exc)) from None


def _cli(where, provider, value, required=CLI_KEYS, optional=(), *, automatic=False):
    if automatic:
        required = ('timeout_seconds', 'environment')
        optional = (*optional, 'executable', 'cli_version')
    value = _fields(value, where, required, optional)
    argv = _texts(value['executable'], f'{where}.executable') if 'executable' in value else ()
    environment = _environment(value['environment'], f'{where}.environment')
    user = dict(environment).get('USER')
    try:
        local = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        raise LocalConfigError(tr('config.uid_account')) from None
    if user != local:
        raise LocalConfigError(tr('config.user_account', where=where))
    try:
        if argv and automatic and not Path(argv[0]).is_absolute():
            raise LocalConfigError(tr('config.absolute_executable', where=f'{where}.executable'))
        executable = ((argv[0] if automatic else _executable(argv[0], f'{where}.executable'), *argv[1:])
                      if argv else ())
        return CLIConfig(provider, executable,
                         _text(value['cli_version'], f'{where}.cli_version') if 'cli_version' in value else None, environment,
                         _number(value['timeout_seconds'], f'{where}.timeout_seconds'),
                         *(_texts(value.get(key, []), f'{where}.{key}', empty=True) for key in TOOL_KEYS))
    except LocalConfigError:
        raise
    except ValueError as exc:
        raise LocalConfigError(f'{where}: {exc}') from None


def _agents(data, *, automatic=False, allow_judge=False):
    """`local-config-2`: the user fixes provider, model and effort of the reviewer."""
    data = _fields(data, 'agents', ('reviewer', 'executor'), ('judge',) if allow_judge else ())
    agents, reviewer = {}, None
    for agent in ('reviewer', 'executor', *(('judge',) if 'judge' in data else ())):
        where = f'agents.{agent}'
        value = data[agent]
        provider = _text(value.get('provider') if isinstance(value, dict) else None, f'{where}.provider')
        if provider not in EFFORTS:
            raise LocalConfigError(tr('config.providers', where=where, allowed=sorted(EFFORTS)))
        if agent in ('reviewer', 'judge'):
            value = _fields(value, where, ('provider', 'model', 'effort',
                            *(('timeout_seconds', 'environment') if automatic else CLI_KEYS)),
                            ('executable', 'cli_version') if automatic else ())
            choice = (_text(value['model'], f'{where}.model'), _text(value['effort'], f'{where}.effort'))
            if agent == 'judge' and not MODEL_FORM.fullmatch(choice[0]):
                raise LocalConfigError(tr('config.models', where=where))
            if agent == 'reviewer':
                reviewer = choice
            if choice[1] not in EFFORTS[provider]:
                raise LocalConfigError(tr('config.efforts', where=where, provider=provider, allowed=list(EFFORTS[provider])))
            optional = ()
        else:
            optional = TOOL_KEYS if provider == 'claude' else ()
        own = ('provider', 'model', 'effort') if agent in ('reviewer', 'judge') else ('provider',)
        agents[agent] = _cli(where, provider, {k: v for k, v in value.items() if k not in own}, optional=optional,
                             automatic=automatic)
    return agents, reviewer


def _presets(data, *, automatic=False):
    """V5: explicit local capabilities; loading does not query remote availability."""
    if not isinstance(data, dict):
        raise LocalConfigError(tr('config.presets_table'))
    presets = {}
    for name, value in data.items():
        where = f'agent_presets.{name}'
        if not PROJECT_ID.fullmatch(name):
            raise LocalConfigError(tr('config.preset_id', where=where))
        value = _fields(value, where, ('provider', 'roles', 'models', 'efforts', 'allow_open_executor',
                        *(('timeout_seconds', 'environment') if automatic else CLI_KEYS)),
                        (*TOOL_KEYS, 'executable', 'cli_version') if automatic else TOOL_KEYS)
        provider = value['provider']
        if not isinstance(provider, str) or provider not in EFFORTS:
            raise LocalConfigError(tr('config.providers', where=where, allowed=sorted(EFFORTS)))
        roles = _texts(value['roles'], f'{where}.roles')
        models, efforts = (_texts(value[key], f'{where}.{key}') for key in ('models', 'efforts'))
        if len(set(roles)) != len(roles) or not set(roles) <= {'reviewer', 'executor'}:
            raise LocalConfigError(tr('config.roles', where=where))
        if (len(set(models)) != len(models) or len(set(efforts)) != len(efforts)
                or any(not MODEL_FORM.fullmatch(model) for model in models)
                or not set(efforts) <= set(EFFORTS[provider])):
            raise LocalConfigError(tr('config.models', where=where))
        _flag(value['allow_open_executor'], f'{where}.allow_open_executor')
        config = _cli(where, provider, {k: v for k, v in value.items() if k in (*CLI_KEYS, *TOOL_KEYS)},
                      optional=TOOL_KEYS if provider == 'claude' else (), automatic=automatic)
        if 'reviewer' in roles and any((config.tools, config.allowed_tools, config.grantable_tools)):
            raise LocalConfigError(tr('config.reviewer_tools', where=where))
        presets[name] = (value, config)
    return presets


def _shell_free(argv, where):
    if not COMMAND_NAME.fullmatch(argv[0]) or argv[0] in SHELLS:
        raise LocalConfigError(tr('config.argv_executable', where=where))
    if any(item in SHELL_TOKENS or '`' in item or '$(' in item for item in argv):
        raise LocalConfigError(tr('config.argv_shell', where=where))
    return argv


def _command(item, label, *, strict):
    """Exact command table (`argv`, `timeout_seconds`, optional `cwd` and `environment`).

    `strict` (local-config-4) also requires a shell-free argv; earlier formats keep their validation."""
    item = _fields(item, label, ('argv', 'timeout_seconds'), ('cwd', 'environment'))
    argv = _texts(item['argv'], f'{label}.argv')
    if strict:
        _shell_free(argv, f'{label}.argv')
    try:
        return Command(argv, _text(item.get('cwd', '.'), f'{label}.cwd'),
                       _environment(item.get('environment', {}), f'{label}.environment'),
                       _number(item['timeout_seconds'], f'{label}.timeout_seconds'))
    except LocalConfigError:
        raise
    except ValueError as exc:
        raise LocalConfigError(f'{label}: {exc}') from None


def _patterns(value, where, *, empty):
    patterns = _texts(value, where, empty=empty)
    for pattern in patterns:
        try:
            relative_path(pattern)
        except ValueError:
            raise LocalConfigError(tr('config.pattern', where=where, pattern=repr(pattern))) from None
    if len(set(patterns)) != len(patterns):
        raise LocalConfigError(tr('config.patterns_repeated', where=where))
    return patterns


def _profile(name, value, *, allow_formatter=False):
    """`local-config-4`: a stack profile declared by the operator; loading it executes nothing (P008-T008).

    Every key that grants effects is explicit (lists may be empty where noted); unknown keys are rejected.
    A validation may declare its JUnit report with `junit = { path, coverage }`."""
    where = f'profiles.{name}'
    if not PROJECT_ID.fullmatch(name):
        raise LocalConfigError(tr('config.name', where=where, pattern=PROJECT_ID.pattern))
    if name in PROFILES:
        raise LocalConfigError(tr('config.name_reserved', where=where))
    formatter_keys = ('formatter_argv', 'formatter_paths')
    # New effects require an explicit format opt-in and the complete, nonempty pair.
    required = PROFILE_KEYS
    if allow_formatter and isinstance(value, dict) and any(key in value for key in formatter_keys):
        required = (*required, *formatter_keys)
    value = _fields(value, where, required, ('sensitive_allowlist',))
    formatter_argv, formatter_paths = (), ()
    if 'formatter_argv' in value:
        formatter_argv = _shell_free(_texts(value['formatter_argv'], f'{where}.formatter_argv'),
                                     f'{where}.formatter_argv')
        formatter_paths = _patterns(value['formatter_paths'], f'{where}.formatter_paths', empty=False)
    commands = {}
    for key in ('preparation', 'validations'):
        items = value[key]
        if not isinstance(items, list) or (key == 'validations' and not items):
            raise LocalConfigError(tr('config.validations_required' if key == 'validations' else 'config.commands_required',
                                      where=f'{where}.{key}'))
        commands[key] = []
        for index, item in enumerate(items):
            label = f'{where}.{key}[{index}]'
            junit = item.get('junit') if key == 'validations' and isinstance(item, dict) else None
            command = _command({k: v for k, v in item.items() if k != 'junit'} if junit is not None else item,
                               label, strict=True)
            if command in (entry for entry, _ in commands[key]):
                raise LocalConfigError(tr('config.command_repeated', where=label))
            if junit is not None:
                junit = _fields(junit, f'{label}.junit', ('path', 'coverage'))
                try:
                    junit = JUnitDeclaration(command, _text(junit['path'], f'{label}.junit.path'),
                                             _text(junit['coverage'], f'{label}.junit.coverage'))
                except ValueError as exc:
                    raise LocalConfigError(f'{label}.junit: {exc}') from None
            commands[key].append((command, junit))
    prefixes = value['allowed_command_prefixes']
    if not isinstance(prefixes, list):
        raise LocalConfigError(tr('config.prefixes', where=where))
    prefixes = tuple(_shell_free(_texts(item, f'{where}.allowed_command_prefixes[{index}]'),
                                 f'{where}.allowed_command_prefixes[{index}]') for index, item in enumerate(prefixes))
    try:
        return ProjectProfile(
            name=name,
            preparation=tuple(command for command, _ in commands['preparation']),
            validations=tuple(command for command, _ in commands['validations']),
            allowed_command_prefixes=prefixes,
            protected_paths=_patterns(value['protected_paths'], f'{where}.protected_paths', empty=False),
            sensitive_paths=_patterns(value['sensitive_paths'], f'{where}.sensitive_paths', empty=False),
            sensitive_allowlist=_patterns(value.get('sensitive_allowlist', []), f'{where}.sensitive_allowlist',
                                          empty=True),
            executor_instructions=_text(value['executor_instructions'], f'{where}.executor_instructions'),
            formatter_argv=formatter_argv, formatter_paths=formatter_paths,
            junit_reports=tuple(junit for _, junit in commands['validations'] if junit is not None),
            data_model_paths=_patterns(value['data_model_paths'], f'{where}.data_model_paths', empty=True))
    except LocalConfigError:
        raise
    except ValueError as exc:
        raise LocalConfigError(f'{where}: {exc}') from None


def _commands(value, where, root, profile, *, strict=False, deferred_root=None):
    value = _fields(value, where, ('executables', 'environment', 'authorize_profile_commands'),
                    ('max_timeout_seconds', 'max_output_bytes', 'authorized'))
    if not isinstance(value['executables'], dict) or not value['executables']:
        raise LocalConfigError(tr('config.executables_table', where=where))
    executables = []
    for name, path in value['executables'].items():
        if isinstance(path, dict) and deferred_root is not None:
            _fields(path, f'{where}.executables.{name}', ('project_venv',))
            tool = path['project_venv']
            if tool not in ('python', 'pytest', 'ruff', 'mypy') or tool != name:
                raise LocalConfigError(tr('config.venv_link', where=where))
            executable = str(deferred_root / '.venv' / 'bin' / tool)
        else:
            executable = _executable(path, f'{where}.executables.{name}')
        executables.append((_text(name, where), executable))
    executables = tuple(sorted(executables))
    if strict:
        for name, path in executables:
            if not COMMAND_NAME.fullmatch(name) or {Path(path).name, Path(path).resolve().name} & SHELLS:
                raise LocalConfigError(tr('config.executable_name', where=f'{where}.executables.{name}'))
    required = profile.preparation + profile.validations
    authorize = _flag(value['authorize_profile_commands'], f'{where}.authorize_profile_commands')
    authorized = required if authorize else ()
    extras = value.get('authorized', [])
    if not isinstance(extras, list):
        raise LocalConfigError(tr('config.authorized', where=where))
    for index, item in enumerate(extras):
        command = _command(item, f'{where}.authorized[{index}]', strict=strict)
        if command not in authorized:
            authorized += (command,)
    if any(command not in authorized for command in required):
        raise LocalConfigError(tr('config.authorize_all', where=where))
    if profile.formatter_argv and not authorize:
        # D133: the formatter receives variable paths, so it does not fit in an exact authorization.
        raise LocalConfigError(tr('config.formatter', where=where))
    try:
        return CommandConfig(str(root), True, authorized, executables,
                             _environment(value['environment'], f'{where}.environment'),
                             formatter_argv=profile.formatter_argv,
                             **{key: value[key] for key in ('max_timeout_seconds', 'max_output_bytes') if key in value})
    except LocalConfigError:
        raise
    except ValueError as exc:
        raise LocalConfigError(f'{where}: {exc}') from None


def _policy(value, where, reviewer, executor_provider):
    """`reviewer` is None for `local-config-1`, whose policy keeps its own planner/reviewer selections."""
    if reviewer is None:
        value = _fields(value, where, ('executor_models', 'executor_efforts', 'planner_model', 'planner_effort',
                        'reviewer_model', 'reviewer_effort'), ('max_revision_cycles', 'planning_mode'))
        selections = tuple(_text(value[key], f'{where}.{key}') for key in
                           ('planner_model', 'planner_effort', 'reviewer_model', 'reviewer_effort'))
        extra = {key: value[key] for key in ('max_revision_cycles', 'planning_mode') if key in value}
    else:
        # D052: explicit settings; the reviewer always plans with its own selection.
        value = _fields(value, where, ('planning_mode', 'executor_mode', 'executor_models', 'executor_efforts'),
                        ('max_revision_cycles',))
        if value['planning_mode'] not in ('agent', 'deterministic'):
            raise LocalConfigError(tr('config.planning_mode', where=where))
        if value['executor_mode'] not in ('catalog', 'open'):
            raise LocalConfigError(tr('config.executor_mode', where=where))
        selections = reviewer * 2
        extra = {key: value[key] for key in ('max_revision_cycles', 'planning_mode', 'executor_mode') if key in value}
        extra['executor_effort_vocabulary'] = EFFORTS[executor_provider]
    if 'max_revision_cycles' in extra and type(extra['max_revision_cycles']) is not int:
        raise LocalConfigError(tr('config.revision_cycles', where=where))
    try:
        return EnginePolicy(_texts(value['executor_models'], f'{where}.executor_models'),
                            _texts(value['executor_efforts'], f'{where}.executor_efforts'), *selections, **extra)
    except LocalConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise LocalConfigError(f'{where}: {exc}') from None


def _outside(path, root):
    return not (path.is_relative_to(root) or root.is_relative_to(path))


def _composition(value, where, state, profiles, *, strict, recipes=None):
    """`local-config-3/4`: commands of a profile under a name, independent of any checkout (D076).

    `profiles` maps every admitted name (built-in, plus declared ones in `local-config-4`) to its profile."""
    if not isinstance(value, dict):
        raise LocalConfigError(tr('config.table_expected', where=where))
    if _text(value.get('profile'), f'{where}.profile') not in profiles:
        raise LocalConfigError(tr('config.profiles', where=where, allowed=sorted(profiles)))
    recipe = value.get('recipe')
    if recipe is not None:
        if not recipes or recipe not in RECIPES or recipe not in recipes or value['profile'] != RECIPES[recipe][1]:
            raise LocalConfigError(tr('config.recipe_v5', where=where))
        if recipe == 'django':
            expected = {name: {'project_venv': name} for name in ('python', 'pytest', 'ruff', 'mypy')}
            if value.get('executables') != expected or value.get('environment') != {} or value.get('authorized'):
                raise LocalConfigError(tr('config.recipe_links', where=where))
        else:
            _typescript_composition(value, where, recipes[recipe])
    elif value['profile'] == 'python-django-recipe' and 'django' in recipes:
        raise LocalConfigError(tr('config.recipe_profile', where=where))
    commands = {key: item for key, item in value.items() if key not in ('profile', 'recipe')}
    # The state directory stands in for a checkout: only the table itself is validated here.
    _commands(commands, where, state, profiles[value['profile']], strict=strict,
              deferred_root=state if recipe == 'django' else None)
    return value['profile'], commands


def _typescript_composition(value, where, recipe):
    """P010-T002 (D142): each task reinstalls with the node/npm and the cache that accredited the preparation.

    The composition keeps its own environment: it must already name that cache, and it is never rewritten."""
    executables = value.get('executables')
    if not isinstance(executables, dict) or not {'node', 'npm'} <= set(executables):
        raise LocalConfigError(tr('config.node_npm', where=where))
    for name in ('node', 'npm'):
        path = _executable(executables[name], f'{where}.executables.{name}')
        if Path(path).resolve() != Path(recipe[f'{name}_executable']).resolve():
            raise LocalConfigError(tr('config.same_executable', where=f'{where}.executables.{name}'))
    environment = value.get('environment')
    if not isinstance(environment, dict) or environment.get('npm_config_cache') != recipe['npm_cache']:
        raise LocalConfigError(tr('config.npm_environment', where=where))


class LocalComposer:
    """Operator authority shared by every project: agents, Git, state and named compositions.

    Composes TOML projects at load and registered projects (D076) at any time; the
    ports and the writer find each checkout's live composition under a lock, so a
    job frozen with another composition or registry version is refused before effects.
    """

    PROJECT_KEYS = ('id', 'root', 'repository_trusted', 'policy')
    OPTIONAL_KEYS = ('tag_kind', 'permission_authority', 'documents')

    def __init__(self, fmt, data, source, state, agents, reviewer, identity, git_executable, engine,
                 compositions, registration, profiles, presets, recipes):
        self.format, self.source, self.state = fmt, source, state
        self.agents_key = 'providers' if fmt == 'local-config-1' else 'agents'
        self._authority = {self.agents_key: data[self.agents_key], 'git': data['git'], 'state_dir': str(state)}
        self.agents, self.reviewer = agents, reviewer
        self.presets, self.recipes = presets, recipes
        # Recipe generation of this format (D168): v5 selects v1 and v6 selects v2; older formats declare none.
        self._recipe_format = fmt if fmt in AGENT_FORMATS else V5
        self.recipe_profiles = {}  # v6/v7: recipe name → profile of its v2 module
        self._recipe_roots, self._receipts = {}, {}
        self.identity, self.git_executable, self.engine = identity, git_executable, engine
        self.compositions = compositions  # name → (profile, raw command table); empty before v3
        self.profiles = profiles  # name → ProjectProfile: built-in ones, plus those declared in v4
        self.declared = tuple(sorted(name for name in profiles if name not in PROFILES))
        # v3–v5: canonical roots under which the UI may register, and the bootstrap ceiling.
        self.roots, self.bootstrap_enabled = registration
        self._lock = Lock()
        self._live = {}
        self._detection_enabled = False

    @property
    def registrable(self):
        return self.format in REGISTRABLE

    def compose(self, item, where, *, registry=None, new_directory=False):
        """Validated `ManagedProject` and its composition, without installing it.

        `registry` is `(version, row_sha256)` of a registered row: it enters the frozen
        hash, so a newer registry version quarantines jobs admitted under the older one.
        `new_directory` is a data-only creation preview: validates on the existing parent,
        freezes the future child's hashes and returns versions/profile, never installable ports.
        """
        if self.format == EDITOR_VERSION:
            if item.get('composition') is not None:
                raise LocalConfigError(tr('profile_proposal.activation_pending'))
            return self._intake(item, where, registry=registry, new_directory=new_directory)
        if self.registrable:
            required, optional = (*self.PROJECT_KEYS, 'composition'), (*self.OPTIONAL_KEYS, 'bootstrap_enabled')
        else:
            required, optional = (*self.PROJECT_KEYS, 'profile', 'commands'), self.OPTIONAL_KEYS
        if self.format in AGENT_FORMATS:
            optional = (*optional, 'agent_selection')
        if self.format in WORK_FORMATS and registry is None and not new_directory:
            optional = (*optional, 'work_language')  # TOML projects only: the UI confirms it in SQLite
        item = _fields(item, where, required, optional)
        work_language = item.get('work_language')
        if work_language is not None and work_language not in LANGUAGES:
            raise LocalConfigError(tr('config.work_language', where=where, allowed=list(LANGUAGES)))
        if item.get('documents', 'v2') != 'v2':
            raise LocalConfigError(tr('config.documents', where=where))
        if _flag(item['repository_trusted'], f'{where}.repository_trusted') is not True:
            raise LocalConfigError(tr('config.trust', where=where))
        # Only the D116 creation preview admits a target that does not exist yet, already validated by the service.
        root = _path(item['root'], f'{where}.root', kind='new_directory' if new_directory else 'directory')
        if not (_outside(self.state, root) and _outside(self.source, root)):
            raise LocalConfigError(tr('config.state_outside', where=where))
        authority = dict(self._authority)
        if self.registrable:
            name = _text(item['composition'], f'{where}.composition')
            if name not in self.compositions:
                raise LocalConfigError(tr('config.compositions_declared', where=where, allowed=sorted(self.compositions)))
            profile_name, table = self.compositions[name]
            authority['composition'] = {name: {'profile': profile_name, **table}}
            recipe = self._recipes_by_composition.get(name)
            if recipe:
                authority['recipe'] = {'config': self.recipes[recipe],
                                       **implementation(recipe_module(recipe, self._recipe_format))}
        else:
            profile_name, table = _text(item['profile'], f'{where}.profile'), item['commands']
            if profile_name not in self.profiles:
                raise LocalConfigError(tr('config.profiles', where=where, allowed=sorted(self.profiles)))
        recipe = self._recipes_by_composition.get(item.get('composition'))
        # v6: a recipe composition runs with its v2 module's own profile (D163/D168), not the built-in one.
        profile = self.recipe_profiles.get(recipe) or self.profiles[profile_name]
        if self.format in PROFILE_FORMATS:
            # P008-T008: the complete profile content (declared or built-in) enters the frozen hash, so
            # changing it quarantines the jobs admitted before. v1–v3 keep their hashes.
            authority['profile'] = asdict(profile)
        bootstrap = _flag(item.get('bootstrap_enabled', False), f'{where}.bootstrap_enabled')
        agents, reviewer, selected = self.effective_agents(item, where)
        if recipe == 'django' and any(dict(agent.environment).get('PYTHONDONTWRITEBYTECODE') != '1'
                                      for agent in agents.values()):
            raise LocalConfigError(tr('config.bytecode', where=where))
        engine_policy = _policy(item['policy'], f'{where}.policy', reviewer, agents['executor'].provider)
        if selected:
            executor = selected['executor']
            if ((engine_policy.executor_mode == 'catalog'
                 and not set(engine_policy.executor_models) <= set(executor['models']))
                    or any(not MODEL_FORM.fullmatch(model) for model in engine_policy.executor_models)
                    or not set(engine_policy.executor_efforts) <= set(executor['efforts'])):
                raise LocalConfigError(tr('config.executor_catalog', where=where))
            if engine_policy.executor_mode == 'open' and not executor['allow_open_executor']:
                raise LocalConfigError(tr('config.open_executor', where=where))
            engine_policy = replace(engine_policy, executor_effort_vocabulary=tuple(executor['efforts']))
            authority['agent_presets'] = selected
        if recipe == 'typescript-web' and not _outside(Path(self.recipes[recipe]['npm_cache']), root):
            raise LocalConfigError(tr('config.npm_cache_outside', where=where))
        # The preview validates the configuration on the existing parent, without building ports for the child.
        commands = _commands(table, f'{where}.commands', root.parent if new_directory else root, profile,
                             strict=self.format in PROFILE_FORMATS, deferred_root=root if recipe == 'django' else None)
        identifier = _text(item['id'], f'{where}.id')
        if not PROJECT_ID.fullmatch(identifier):
            raise LocalConfigError(tr('config.project_id', where=where, pattern=PROJECT_ID.pattern))
        artifacts = self.state / 'artifacts' / identifier
        try:
            cli = CLIProcessAdapter(agents, artifacts)
        except ValueError as exc:
            raise LocalConfigError(f'{self.agents_key}: {exc}') from None
        if recipe == 'django':
            commands = replace(commands, environment=(('PYTHONDONTWRITEBYTECODE', '1'), ('PYTHONNOUSERSITE', '1')))
        runner = ManagedCommandRunner(commands)
        frozen = {'project': item, **authority}
        if registry is not None:
            frozen['registry'] = {'version': registry[0], 'row_sha256': registry[1]}
        try:
            digest = hashlib.sha256(freeze(frozen).encode()).hexdigest()
        except (TypeError, ValueError):
            raise LocalConfigError(tr('config.toml_values', where=where)) from None
        # D088: the documentary layout is mandatory. Its version enters the frozen ones, so a job admitted
        # before (optional contract or no contract) is quarantined instead of running with another layout.
        versions = {'engine': f'harness-local-{self.engine}', 'evidence': 'git-1', 'provider_cli': None,
                    'local_config': self.format, 'profile': profile.name, 'local_config_sha256': digest,
                    'document_layout': DOCUMENT_LAYOUT,
                    **({'project_registry': str(registry[0])} if registry is not None else {}),
                    **({'project_registry_id': identifier, 'project_registry_sha256': registry[1]}
                       if registry is not None and self.format in AGENT_FORMATS else {}),
                    **cli.frozen_versions(), **runner.frozen_versions(),
                    **({'project_recipe': recipe_module(recipe, self._recipe_format).VERSION,
                        'recipe_config_sha256': hashlib.sha256(freeze(authority['recipe']).encode()).hexdigest()}
                       if recipe else {})}
        if 'judge' in agents:
            versions.update(judge_model=self.judge_selection['model'], judge_effort=self.judge_selection['effort'])
        if self.format in AUTOMATIC_FORMATS:
            choice = item.get('agent_selection')
            declarations = ({role: self.presets[preset['preset_id']][1] for role, preset in choice.items()}
                            if choice is not None else self.agents)
            for role, declaration in declarations.items():
                versions[f'{role}_cli_version_source'] = ('automatic' if declaration.cli_version is None
                                                         else 'legacy-assertion')
                versions[f'{role}_cli_discovery'] = 'PATH' if not declaration.executable else 'explicit'
        if new_directory:
            commands_snapshot = {**config_payload(commands), 'checkout': str(root)}
            versions['command_config_sha256'] = hashlib.sha256(freeze(commands_snapshot).encode()).hexdigest()
            preview = ManagedProject(identifier, ProjectContext(root.parent, profile, engine_policy, documents='v2'),
                                     versions, item.get('permission_authority'), item.get('tag_kind', 'lightweight'),
                                     bootstrap)
            validate_projects(ManagedConfig((preview,), ports_factory=self.ports, commit_factory=self.writer))
            return {'versions': versions, 'profile': profile.name, 'profile_details': _profile_view(profile),
                    'agents': agents_view(preview),
                    'composition': next(c for c in self.options()['compositions'] if c['name'] == name)}
        context = ProjectContext(root, profile, engine_policy, documents='v2', work_language=work_language)
        project = ManagedProject(identifier, context, versions, item.get('permission_authority'),
                                 item.get('tag_kind', 'lightweight'), bootstrap)
        return project, (identifier, versions, commands, artifacts, agents,
                         (dict(item), where, registry))

    def _intake(self, item, where, *, registry, new_directory):
        """No stack, runner or invented composition. Directory creation/activation is joined in T009."""
        from my_harness.core.engine.context import IntakeContext
        item = {'composition': None, **item}
        item = _fields(item, where, (*self.PROJECT_KEYS, 'composition'),
                       (*self.OPTIONAL_KEYS, 'bootstrap_enabled', 'agent_selection'))
        root = _path(item['root'], f'{where}.root', kind='new_directory' if new_directory else 'directory')
        if not (_outside(self.state, root) and _outside(self.source, root)):
            raise LocalConfigError(tr('config.state_outside', where=where))
        if _flag(item['repository_trusted'], f'{where}.repository_trusted') is not True:
            raise LocalConfigError(tr('config.trust', where=where))
        if item.get('documents', 'v2') != 'v2' or item.get('permission_authority') is not None:
            raise LocalConfigError(tr('profile_proposal.required'))
        identifier = _text(item['id'], f'{where}.id')
        if not PROJECT_ID.fullmatch(identifier):
            raise LocalConfigError(tr('config.project_id', where=where, pattern=PROJECT_ID.pattern))
        agents, reviewer, selected = self.effective_agents(item, where)
        policy = _policy(item['policy'], f'{where}.policy', reviewer, agents['executor'].provider)
        if selected:
            executor = selected['executor']
            if ((policy.executor_mode == 'catalog' and not set(policy.executor_models) <= set(executor['models']))
                    or not set(policy.executor_efforts) <= set(executor['efforts'])
                    or (policy.executor_mode == 'open' and not executor['allow_open_executor'])):
                raise LocalConfigError(tr('config.executor_catalog', where=where))
            policy = replace(policy, executor_effort_vocabulary=tuple(executor['efforts']))
        artifacts = self.state / 'artifacts' / identifier
        cli = CLIProcessAdapter(agents, artifacts)
        frozen = {'project': item, **self._authority, 'agent_presets': selected,
                  'registry': registry, 'capabilities': 'project-intake-1'}
        versions = {'engine': f'harness-local-{self.engine}', 'evidence': 'git-1',
                    'commands': 'intake-none-1', 'local_config': self.format,
                    'local_config_sha256': hashlib.sha256(freeze(frozen).encode()).hexdigest(),
                    'document_layout': DOCUMENT_LAYOUT, **cli.frozen_versions()}
        if 'judge' in agents:
            versions.update(judge_model=self.judge_selection['model'], judge_effort=self.judge_selection['effort'])
        if registry is not None:
            versions.update(project_registry=str(registry[0]), project_registry_id=identifier,
                            project_registry_sha256=registry[1])
        selection = item.get('agent_selection')
        declarations = ({role: self.presets[choice['preset_id']][1] for role, choice in selection.items()}
                        if selection is not None else self.agents)
        for role, declaration in declarations.items():
            versions[f'{role}_cli_version_source'] = 'automatic' if declaration.cli_version is None else 'legacy-assertion'
            versions[f'{role}_cli_discovery'] = 'PATH' if not declaration.executable else 'explicit'
        if new_directory:
            return {'versions': versions, 'profile': None, 'profile_details': {'sha256': None},
                    'agents': agents_view(ManagedProject(identifier, IntakeContext(root.parent, policy), versions)),
                    'composition': None}
        project = ManagedProject(identifier, IntakeContext(root, policy), versions, None,
                                 item.get('tag_kind', 'lightweight'),
                                 _flag(item.get('bootstrap_enabled', False), f'{where}.bootstrap_enabled'))
        return project, (identifier, versions, None, artifacts, agents, (dict(item), where, registry))

    def compose_profile(self, intake, data, receipt, reference):
        """Compose the verified own profile using the existing command/CLI contracts, without installing it."""
        from copy import copy
        shadow = copy(self)
        shadow.format = VERSION
        shadow.profiles = {data['profile_name']: _profile(data['profile_name'], data['profile'], allow_formatter=True)}
        shadow.compositions = {'owned': (data['profile_name'], data['commands'])}
        shadow._recipes_by_composition = {}
        from my_harness.services.configuration import JUDGE_PROJECT
        shadow.agents, shadow.reviewer = _agents(data['agents'], automatic=True,
                                                 allow_judge=data['format'] == JUDGE_PROJECT)
        shadow.judge_selection = data['agents'].get('judge')
        original = self._live[intake.context.root][5]
        item = {key: value for key, value in original[0].items() if key not in ('profile', 'commands')}
        item.update(composition='owned', policy=data['policy'])
        item.pop('agent_selection', None)
        project, composition = shadow.compose(item, original[1], registry=original[2])
        versions = {**project.versions, 'local_config': EDITOR_VERSION,
                    'project_configuration': data['format'],
                    'project_configuration_revision': str(reference['revision']),
                    'project_configuration_sha256': reference['sha256'],
                    'project_environment_sha256': hashlib.sha256(freeze(receipt).encode()).hexdigest()}
        versions['local_config_sha256'] = hashlib.sha256(freeze({
            'base': intake.versions['local_config_sha256'], 'configuration': reference, 'data': data}).encode()).hexdigest()
        project = replace(project, versions=versions, context=replace(project.context,
                          work_language=intake.context.work_language))
        return project, (composition[0], versions, *composition[2:5], original)

    def effective_agents(self, item, where):
        selection = item.get('agent_selection')
        if selection is None:
            return self._resolve_agents(self.agents), self.reviewer, None
        selection = _fields(selection, f'{where}.agent_selection', ('reviewer', 'executor'))
        agents, selected, reviewer = {}, {}, None
        for role in ('reviewer', 'executor'):
            label = f'{where}.agent_selection.{role}'
            choice = _fields(selection[role], label, ('preset_id', 'model', 'effort') if role == 'reviewer'
                             else ('preset_id',))
            name = _text(choice['preset_id'], f'{label}.preset_id')
            if name not in self.presets or role not in self.presets[name][0]['roles']:
                raise LocalConfigError(tr('config.preset_role', where=label, preset=name))
            preset, agents[role] = self.presets[name]
            selected[role] = preset
            if role == 'reviewer':
                reviewer = tuple(_text(choice[key], f'{label}.{key}') for key in ('model', 'effort'))
                if reviewer[0] not in preset['models'] or reviewer[1] not in preset['efforts']:
                    raise LocalConfigError(tr('config.reviewer_choice', where=label))
        return self._resolve_agents(agents), reviewer, selected

    def _resolve_agents(self, agents):
        if self.format not in AUTOMATIC_FORMATS or not self._detection_enabled:
            return agents
        resolved = {}
        for role, declaration in agents.items():
            config = discover(declaration)
            report = preflight_config(config, access='write' if role == 'executor' else 'read')
            if not report['available']:
                raise CompatibilityError(report['diagnostics'][0]['code'], **(
                    {'provider': config.provider, 'observed': report['observed_version'],
                     'minimum': report['minimum_version']} if report['diagnostics'][0]['code'] == 'minimum_version' else {}))
            resolved[role] = replace(config, cli_version=report['observed_version'])
        return resolved

    def resolve_config(self, config):
        """Explicit startup step; parsing remains data-only, only effective project roles are probed."""
        if self.format not in AUTOMATIC_FORMATS:
            return config
        self._detection_enabled = True
        projects = tuple(self.refresh(project, force=True) for project in config.projects)
        return replace(config, projects=projects)

    def refresh(self, project, *, force=False):
        """New work observes updates; unchanged launch files may reuse the admission observation.

        Per-attempt preflight never reuses it. Stored job identities are never changed here.
        """
        if self.format not in AUTOMATIC_FORMATS or not self._detection_enabled:
            return project
        with self._lock:
            composition = self._live[project.context.root]
        agents = composition[4]
        if not force:
            try:
                selection = composition[5][0].get('agent_selection')
                declarations = ({role: self.presets[choice['preset_id']][1] for role, choice in selection.items()}
                                if selection is not None else self.agents)
                if all(agents[role].cli_version and launch_identity(discover(config))[1]
                       == project.versions.get(f'{role}_cli_launch_sha256') for role, config in declarations.items()):
                    return project
            except (OSError, ValueError):
                pass
        item, where, registry = composition[5]
        return self.install(self.compose(item, where, registry=registry))

    def install(self, composed):
        project, composition = composed
        with self._lock:
            self._live[project.context.root] = composition
        known = recipe_version(project.versions.get('project_recipe'))
        if known:
            self._recipe_roots[project.context.root] = self.recipes[known[0]]
        return project

    def forget(self, root):
        with self._lock:
            self._live.pop(root, None)

    def _composed(self, context, versions):
        with self._lock:
            current = self._live.get(context.root)
        if current is None:
            raise JournalError(tr('config.no_composition'))
        identifier, frozen, commands, artifacts, agents, _ = current
        if any(versions.get(key) != value for key, value in frozen.items()):
            raise JournalError(tr('config.composition_changed', project=identifier))
        return commands, artifacts, agents

    def ports(self, context, versions):
        commands, artifacts, agents = self._composed(context, versions)
        if commands is None:
            return CLIProcessAdapter(agents, artifacts), None, GitWorkspace(self.identity, executable=self.git_executable)
        if versions.get('project_recipe') or versions.get('project_configuration'):
            from my_harness.adapters.preparation import PreparedCommandRunner
            runner = PreparedCommandRunner(commands, self._receipts.get(context.root), versions)
        else:
            runner = ManagedCommandRunner(commands)
        return (CLIProcessAdapter(agents, artifacts), runner,
                GitWorkspace(self.identity, executable=self.git_executable))

    def writer(self, context, versions):
        self._composed(context, versions)
        return GitWorkspace(self.identity, executable=self.git_executable)

    def options(self):
        """What the UI may choose; executables and environment values never leave the file."""
        return {'format': self.format, 'roots': [str(root) for root in self.roots],
                'bootstrap_enabled': self.bootstrap_enabled,
                'executor_provider': self.agents['executor'].provider,
                'reviewer_provider': self.agents['reviewer'].provider,
                'executor_effort_vocabulary': list(EFFORTS[self.agents['executor'].provider]),
                'agent_presets': [{'id': name, **{key: value[key] for key in
                                  ('provider', 'roles', 'models', 'efforts', 'allow_open_executor')}}
                                  for name, (value, _) in sorted(self.presets.items())],
                'compositions': [{'name': name, 'profile': profile,
                                  'executables': sorted(table['executables']),
                                  'environment_keys': sorted(table['environment']),
                                  'authorize_profile_commands': table['authorize_profile_commands'],
                                  'extra_commands': [list(item['argv']) for item in table.get('authorized', [])]}
                                 for name, (profile, table) in sorted(self.compositions.items())]}


def _build(data, source, *, allow_empty_compositions=False, editor=False, allow_judge=False):
    if not isinstance(data, dict) or data.get('format') not in ((*FORMATS, EDITOR_VERSION) if editor else FORMATS):
        raise LocalConfigError(tr('config.format', allowed=list(FORMATS)))
    fmt = data['format']
    agents_key = 'providers' if fmt == 'local-config-1' else 'agents'
    if fmt in REGISTRABLE:
        data = _fields(data, tr('config.root_table'), ('format', 'service', 'git', 'agents', 'registration', 'compositions'),
                       ('projects', 'profiles', 'agent_presets', 'recipes') if fmt in AGENT_FORMATS else
                       ('projects', 'profiles') if fmt in PROFILE_FORMATS else ('projects',))
    else:
        data = _fields(data, tr('config.root_table'), ('format', 'service', 'git', agents_key, 'projects'))
    service = _fields(data['service'], 'service', ('state_dir', 'supervisor'), ('lease_seconds', 'poll_seconds'))
    state = _path(service['state_dir'], 'service.state_dir', kind='directory')
    git = _fields(data['git'], 'git', ('executable', 'author_name', 'author_email'))
    try:
        identity = GitIdentity(git['author_name'], git['author_email'])
    except ValueError as exc:
        raise LocalConfigError(f'git: {exc}') from None
    git_executable = _executable(git['executable'], 'git.executable')
    if fmt == 'local-config-1':
        providers = _fields(data['providers'], 'providers', ('codex', 'claude'))
        agents = {'reviewer': _cli('providers.codex', 'codex', providers['codex']),
                  'executor': _cli('providers.claude', 'claude', providers['claude'], optional=TOOL_KEYS)}
        reviewer = None
    else:
        agents, reviewer = _agents(data['agents'], automatic=fmt in AUTOMATIC_FORMATS, allow_judge=allow_judge)
    presets = _presets(data.get('agent_presets', {}), automatic=fmt in AUTOMATIC_FORMATS)
    compositions, registration = {}, ((), False)
    recipes = {}
    if 'recipes' in data:
        raw = _fields(data['recipes'], 'recipes', (), tuple(RECIPES))
        if 'django' in raw:
            entry = _fields(raw['django'], 'recipes.django',
                            ('python_executable', 'python_version', 'installer_executable', 'installer_version',
                             'timeout_seconds', 'max_output_bytes', 'allow_network'), ('wheelhouse',))
            entry = dict(entry)
            for key in ('python_executable', 'installer_executable'):
                entry[key] = _executable(entry[key], f'recipes.django.{key}')
                if {Path(entry[key]).name, Path(entry[key]).resolve().name} & SHELLS:
                    raise LocalConfigError(tr('config.django_tools'))
            if not re.fullmatch(r'3\.(11|12|13)\.[0-9]+', _text(entry['python_version'], 'recipes.django.python_version')):
                raise LocalConfigError(tr('config.django_python'))
            if not re.fullmatch(r'0\.[0-9]+\.[0-9]+', _text(entry['installer_version'], 'recipes.django.installer_version')):
                raise LocalConfigError(tr('config.django_uv'))
            if not 120 <= _number(entry['timeout_seconds'], 'recipes.django.timeout_seconds') <= 1800:
                raise LocalConfigError(tr('config.timeout', where='recipes.django'))
            if type(entry['max_output_bytes']) is not int or not 1024 <= entry['max_output_bytes'] <= 1048576:
                raise LocalConfigError(tr('config.output', where='recipes.django'))
            _flag(entry['allow_network'], 'recipes.django.allow_network')
            if 'wheelhouse' in entry:
                entry['wheelhouse'] = str(_path(entry['wheelhouse'], 'recipes.django.wheelhouse', kind='directory'))
            recipes['django'] = entry
        if 'typescript-web' in raw:
            recipes['typescript-web'] = _typescript_recipe(raw['typescript-web'], state)
    profiles = {name: factory() for name, factory in PROFILES.items()}
    recipe_profiles = {}
    if fmt in WORK_FORMATS:
        # D168: the v2 profiles are part of each v2 fingerprint; the built-in `typescript-web` stays for compositions
        # without a recipe.
        recipe_profiles = {name: recipe_module(name, fmt).profile() for name in recipes}
    if 'django' in recipes:
        from my_harness.recipes.django import profile
        # P009-T019 (D133): the formatter is declared here and not in recipes/django.py, whose text is part of the
        # recipe fingerprint that binds the preparation receipts already issued. v2 keeps the same formatter.
        base = recipe_profiles.get('django') or profile()
        profiles['python-django-recipe'] = replace(base, formatter_argv=('ruff', 'format', '--'),
                                                   formatter_paths=('*.py',))
        if fmt in WORK_FORMATS:
            recipe_profiles['django'] = profiles['python-django-recipe']
    declared = data.get('profiles', {})
    if not isinstance(declared, dict):
        raise LocalConfigError(tr('config.profiles_table'))
    for name, value in declared.items():
        if name == 'python-django-recipe' and 'django' in recipes:
            raise LocalConfigError(tr('config.recipe_profile_reserved'))
        profiles[name] = _profile(name, value, allow_formatter=fmt in (VERSION, EDITOR_VERSION))
    if fmt in REGISTRABLE:
        if not isinstance(data['compositions'], dict) or (not data['compositions'] and not allow_empty_compositions):
            raise LocalConfigError(tr('config.compositions_required'))
        for name, value in data['compositions'].items():
            if not PROJECT_ID.fullmatch(name):
                raise LocalConfigError(tr('config.name', where=f'compositions.{name}', pattern=PROJECT_ID.pattern))
            compositions[name] = _composition(value, f'compositions.{name}', state, profiles,
                                               strict=fmt in PROFILE_FORMATS, recipes=recipes)
        table = _fields(data['registration'], 'registration', ('roots', 'bootstrap_enabled'))
        roots = tuple(_path(item, 'registration.roots', kind='directory')
                      for item in _texts(table['roots'], 'registration.roots', empty=True))
        if len(set(roots)) != len(roots):
            raise LocalConfigError(tr('config.roots_repeated'))
        registration = (roots, _flag(table['bootstrap_enabled'], 'registration.bootstrap_enabled'))
    items = data.get('projects', [])
    if not isinstance(items, list) or (not items and fmt not in REGISTRABLE):
        raise LocalConfigError(tr('config.projects_required'))
    try:
        engine = importlib.metadata.version('my-harness')
    except importlib.metadata.PackageNotFoundError:
        raise LocalConfigError(tr('config.package_version')) from None

    composer = LocalComposer(fmt, data, source, state, agents, reviewer, identity, git_executable, engine,
                             compositions, registration, profiles, presets, recipes)
    composer.judge_selection = data.get('agents', {}).get('judge')
    composer._recipes_by_composition = {name: value['recipe'] for name, value in data.get('compositions', {}).items()
                                       if value.get('recipe')}
    composer.recipe_profiles = recipe_profiles
    projects = []
    for index, item in enumerate(items):
        project, composition = composer.compose(item, f'projects[{index}]')
        if project.id in {p.id for p in projects} or project.context.root in {p.context.root for p in projects}:
            raise LocalConfigError(tr('config.projects_duplicate', where=f'projects[{index}]'))
        projects.append(composer.install((project, composition)))

    config = ManagedConfig(tuple(projects), ports_factory=composer.ports, commit_factory=composer.writer,
                           supervisor=_flag(service['supervisor'], 'service.supervisor'),
                           lease_seconds=_number(service.get('lease_seconds', 30.0), 'service.lease_seconds'),
                           poll_seconds=_number(service.get('poll_seconds', 0.5), 'service.poll_seconds'),
                           migrations_dir=state / 'migrations', registrar=composer)
    try:
        validate_projects(config)
    except ValueError as exc:
        raise LocalConfigError(str(exc)) from None
    return config, agents


def _typescript_recipe(value, state):
    """P010-T002 (D142): `[recipes.typescript-web]`, operator authority for `typescript-web-recipe-1` (v5) or
    `typescript-web-recipe-2` (v6, D168): the same keys."""
    where = 'recipes.typescript-web'
    entry = dict(_fields(value, where, ('node_executable', 'node_version', 'npm_executable', 'npm_version', 'npm_cache',
                                        'timeout_seconds', 'max_output_bytes', 'allow_network')))
    for key in ('node_executable', 'npm_executable'):
        entry[key] = _executable(entry[key], f'{where}.{key}')
        if {Path(entry[key]).name, Path(entry[key]).resolve().name} & SHELLS:
            raise LocalConfigError(tr('config.node_tools', where=where))
    for key in ('node_version', 'npm_version'):
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', _text(entry[key], f'{where}.{key}')):
            raise LocalConfigError(tr('config.exact_version', where=f'{where}.{key}'))
    entry['npm_cache'] = str(_path(entry['npm_cache'], f'{where}.npm_cache', kind='directory'))
    if not _outside(Path(entry['npm_cache']), state):
        raise LocalConfigError(tr('config.npm_cache_state', where=where))
    if not 120 <= _number(entry['timeout_seconds'], f'{where}.timeout_seconds') <= 1800:
        raise LocalConfigError(tr('config.timeout', where=where))
    if type(entry['max_output_bytes']) is not int or not 1024 <= entry['max_output_bytes'] <= 1048576:
        raise LocalConfigError(tr('config.output', where=where))
    _flag(entry['allow_network'], f'{where}.allow_network')
    return entry


def build(data, source) -> ManagedConfig:
    return _build(data, source)[0]


def load_local_config(path) -> ManagedConfig:
    path = Path(path)
    return build(_read(path), path)


def inspect_local_config(path) -> tuple[ManagedConfig, dict[str, CLIConfig]]:
    """For check-config: defaults and every role admitted by a V5 preset."""
    path = Path(path)
    config, agents = _build(_read(path), path)
    return config, {**agents, **{f'preset.{name}.{role}': cli
                               for name, (value, cli) in config.registrar.presets.items()
                               for role in value['roles']}}


def from_environment() -> ManagedConfig:
    """Development entry for `HARNESS_MANAGED_CONFIG=my_harness.services.local_config:from_environment`."""
    value = os.environ.get(CONFIG_ENV)
    if not value:
        raise LocalConfigError(tr('config.env', variable=CONFIG_ENV))
    return load_local_config(value)


def _profile_view(profile: ProjectProfile) -> dict:
    """P008-T008: a declared profile's content hash and the argv the operator confirms."""
    view = {'sha256': hashlib.sha256(freeze(asdict(profile)).encode()).hexdigest(),
            'preparation': [list(command.argv) for command in profile.preparation],
            'validations': [list(command.argv) for command in profile.validations],
            'junit_reports': [item.path for item in profile.junit_reports],
            'data_model_paths': list(profile.data_model_paths)}
    if profile.formatter_argv:
        view.update(formatter_argv=list(profile.formatter_argv), formatter_paths=list(profile.formatter_paths))
    return view


def summary(config: ManagedConfig) -> dict:
    """Identifiers, roots and frozen versions only: environment values never leave the file."""
    registrar = config.registrar
    return {'format': registrar.format, 'supervisor': config.supervisor,
            'registration': registrar.options() if registrar.registrable else None,
            'profiles': {name: _profile_view(registrar.profiles[name]) for name in registrar.declared},
            'projects': [{'id': p.id, 'root': str(p.context.root), 'profile': p.context.profile.name,
                          'policy': asdict(p.context.policy), 'agents': agents_view(p), 'versions': dict(p.versions),
                          'tag_kind': p.tag_kind, 'permission_authority': p.permission_authority is not None,
                          'documents': p.context.documents, 'bootstrap_enabled': p.bootstrap_enabled,
                          'work_language': p.context.work_language}
                         for p in config.projects]}
