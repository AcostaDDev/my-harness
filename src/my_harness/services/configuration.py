"""Data-only editor formats (D217). The legacy loader and its hashes stay 1–8.

These documents never install ports or discover clients. A draft may be incomplete;
only a fully checked document may become VALIDATED. Runtime wiring belongs to T005/T009.
"""
import copy
import hashlib
import re
import tomllib

from my_harness.i18n import tr
from my_harness.services import local_config as legacy

GLOBAL = 'local-config-9'
PROJECT = 'project-config-1'
MAX_BYTES = legacy.MAX_BYTES
SECRET_KEY = re.compile(r'(^|[_-])(password|secret|token|credentials?|api[_-]?key|private[_-]?key)($|[_-])', re.I)


def fields(*names):
    return dict.fromkeys(names)


COMMAND = fields('argv', 'timeout_seconds', 'cwd', 'environment')
PROFILE = {**fields(*legacy.PROFILE_KEYS, 'sensitive_allowlist', 'formatter_argv', 'formatter_paths'),
           'preparation': [COMMAND], 'validations': [{**COMMAND, 'junit': fields('path', 'coverage')}]}
COMMANDS = {**fields('executables', 'environment', 'authorize_profile_commands', 'max_timeout_seconds',
                    'max_output_bytes'), 'authorized': [COMMAND]}
CLI = fields(*legacy.CLI_KEYS, *legacy.TOOL_KEYS, 'provider')
AGENTS = {'reviewer': {**CLI, **fields('model', 'effort')}, 'executor': CLI}
POLICY = fields('planning_mode', 'executor_mode', 'executor_models', 'executor_efforts', 'max_revision_cycles')
GLOBAL_SHAPE = {
    'format': None, 'service': fields('state_dir', 'supervisor', 'lease_seconds', 'poll_seconds'),
    'git': fields('executable', 'author_name', 'author_email'), 'agents': AGENTS,
    'registration': fields('roots', 'bootstrap_enabled'), 'profiles': {'*': PROFILE},
    'compositions': {'*': {**COMMANDS, **fields('profile', 'recipe')}},
    'agent_presets': {'*': {**CLI, **fields('roles', 'models', 'efforts', 'allow_open_executor')}},
    'recipes': {'django': fields('python_executable', 'python_version', 'installer_executable', 'installer_version',
                                'timeout_seconds', 'max_output_bytes', 'allow_network', 'wheelhouse'),
                'typescript-web': fields('node_executable', 'node_version', 'npm_executable', 'npm_version',
                                         'npm_cache', 'timeout_seconds', 'max_output_bytes', 'allow_network')},
}
PROJECT_SHAPE = {'format': None, 'project': fields('id', 'root'), 'global': fields('revision', 'sha256'),
                 'profile_name': None, 'profile': PROFILE, 'commands': COMMANDS, 'policy': POLICY,
                 'agents': AGENTS, 'provenance': fields('source', 'sha256'),
                 'edit': {'head': None, 'documents': {'*': None}, 'preparation_plan': None}}


def shape(value, schema):
    """Incomplete drafts may omit fields, but never introduce unknown permissions/keys."""
    if isinstance(schema, dict):
        if not isinstance(value, dict) or ('*' not in schema and set(value) - set(schema)):
            raise ValueError(tr('configuration.unknown_fields'))
        for key, item in value.items():
            shape(item, schema.get(key, schema.get('*')))
    elif isinstance(schema, list):
        if not isinstance(value, list):
            raise ValueError(tr('configuration.command_list'))
        for item in value:
            shape(item, schema[0])


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def secretless(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY.search(key):
                raise ValueError(tr('configuration.credential_fields'))
            secretless(item)
    elif isinstance(value, list):
        for item in value:
            secretless(item)
    elif isinstance(value, str) and (value.startswith(('Bearer ', 'sk-', 'ghp_', 'github_pat_'))
                                   or 'PRIVATE KEY-----' in value):
        raise ValueError(tr('configuration.credentials'))


def parse(text, scope, *, validated=True):
    if (scope != 'global' and (not isinstance(scope, str) or not scope.startswith('project:')
                              or not legacy.PROJECT_ID.fullmatch(scope[8:]))):
        raise ValueError(tr('configuration.scope'))
    if not isinstance(text, str) or '\0' in text or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError(tr('configuration.size'))
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise ValueError(tr('configuration.toml')) from None
    secretless(data)
    shape(data, GLOBAL_SHAPE if scope == 'global' else PROJECT_SHAPE)
    if scope == 'global':
        required = ('format', 'service', 'git', 'agents', 'registration')
        optional = ('profiles', 'compositions', 'agent_presets', 'recipes')
        fmt = GLOBAL
    else:
        required = ('format', 'project', 'global', 'profile_name', 'profile', 'commands', 'policy', 'agents')
        optional = ('provenance', 'edit')
        fmt = PROJECT
    legacy._fields(data, 'configuration', required if validated else ('format',),
                   optional if validated else (*required[1:], *optional))
    if data['format'] != fmt:
        raise ValueError(tr('configuration.explicit_import'))
    if not validated:
        return data
    if scope == 'global':
        candidate = copy.deepcopy(data)
        candidate['format'] = legacy.VERSION
        candidate.setdefault('compositions', {})
        # Reuse all v8 field/command checks without constructing a fake project or changing its hashes.
        legacy._build(candidate, None, allow_empty_compositions=True)
    else:
        project = legacy._fields(data['project'], 'project', ('id', 'root'))
        if project['id'] != scope.removeprefix('project:'):
            raise ValueError(tr('configuration.scope_identity'))
        legacy._path(project['root'], 'project.root', kind='directory')
        ref = legacy._fields(data['global'], 'global', ('revision', 'sha256'))
        if (type(ref['revision']) is not int or ref['revision'] < 1 or not isinstance(ref['sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', ref['sha256'])):
            raise ValueError(tr('configuration.global_reference'))
        profile = legacy._profile(legacy._text(data['profile_name'], 'profile_name'), data['profile'], allow_formatter=True)
        agents, reviewer = legacy._agents(data['agents'], automatic=True)
        legacy._policy(data['policy'], 'policy', reviewer, agents['executor'].provider)
        legacy._commands(data['commands'], 'commands', project['root'], profile, strict=True)
        if 'edit' in data:
            edit = legacy._fields(data['edit'], 'edit', ('head', 'documents', 'preparation_plan'))
            if (not isinstance(edit['head'], str) or not re.fullmatch(r'[a-f0-9]{40,64}', edit['head'])
                    or not isinstance(edit['documents'], dict) or not 1 <= len(edit['documents']) <= 8
                    or any(not isinstance(v, str) or not re.fullmatch(r'[a-f0-9]{64}', v)
                           for v in edit['documents'].values())):
                raise ValueError(tr('configuration.invalid_edit'))
            from my_harness.core.engine.context import relative_path
            for path in edit['documents']:
                relative_path(path)
        if 'provenance' in data:
            legacy._fields(data['provenance'], 'provenance', ('source', 'sha256'))
            legacy._text(data['provenance']['source'], 'provenance.source')
            if (not isinstance(data['provenance']['sha256'], str)
                    or not re.fullmatch(r'[a-f0-9]{64}', data['provenance']['sha256'])):
                raise ValueError(tr('configuration.provenance'))
    return data
