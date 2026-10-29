"""Data-only editor formats (D217). The legacy loader and its hashes stay 1–8.

These documents never install ports or discover clients. A draft may be incomplete;
only a fully checked document may become VALIDATED. Runtime wiring belongs to T005/T009.
`local-config-10` / `project-config-2` (P001-T003, D255/D259) add only billing metadata: an explicit format
choice, never a load-time conversion. Billing is not executable configuration and never selects authentication.
"""
import copy
import hashlib
import re
import tomllib

from my_harness.i18n import tr
from my_harness.services import local_config as legacy

GLOBAL = 'local-config-9'
PROJECT = 'project-config-1'
BILLING_GLOBAL = 'local-config-10'
BILLING_PROJECT = 'project-config-2'
GLOBALS = (GLOBAL, BILLING_GLOBAL)
PROJECTS = (PROJECT, BILLING_PROJECT)
BASES = ('api_usd', 'enterprise_usd', 'token_credit', 'subscription_equivalent')
PROFILE_NAME = re.compile(r'[a-z0-9][a-z0-9_-]{0,63}\Z')
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
BILLING_PROFILE = {**fields('provider', 'platform', 'product', 'scheme', 'unit', 'basis', 'references'),
                   'conditions': {'*': fields('value', 'source')}}
SELECTION = fields('reviewer', 'executor')
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
    'billing': {'profiles': {'*': BILLING_PROFILE}, 'defaults': SELECTION},
}
PROJECT_SHAPE = {'format': None, 'project': fields('id', 'root'), 'global': fields('revision', 'sha256'),
                 'profile_name': None, 'profile': PROFILE, 'commands': COMMANDS, 'policy': POLICY,
                 'agents': AGENTS, 'provenance': fields('source', 'sha256'),
                 'edit': {'head': None, 'documents': {'*': None}, 'preparation_plan': None},
                 'billing': SELECTION}


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
        optional = ('profiles', 'compositions', 'agent_presets', 'recipes', 'billing')
        formats, billing = GLOBALS, BILLING_GLOBAL
    else:
        required = ('format', 'project', 'global', 'profile_name', 'profile', 'commands', 'policy', 'agents')
        optional = ('provenance', 'edit', 'billing')
        formats, billing = PROJECTS, BILLING_PROJECT
    legacy._fields(data, 'configuration', required if validated else ('format',),
                   optional if validated else (*required[1:], *optional))
    if data['format'] not in formats:
        raise ValueError(tr('configuration.explicit_import'))
    if 'billing' in data and data['format'] != billing:
        raise ValueError(tr('configuration.billing_format'))
    if not validated:
        return data
    if scope == 'global':
        candidate = runtime(data)
        candidate['format'] = legacy.VERSION
        # Reuse all v8 field/command checks without constructing a fake project or changing its hashes.
        legacy._build(candidate, None, allow_empty_compositions=True)
        agents, _ = legacy._agents(data['agents'], automatic=True)
        billing_profiles(data.get('billing'), {role: agent.provider for role, agent in agents.items()})
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
        if 'billing' in data:
            # Selections name global profiles; existence/provider are checked when the binding is resolved.
            selection(data['billing'])
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


def runtime(data):
    """The executable part of an editor document: billing metadata removed, v10 composed exactly as v9."""
    candidate = copy.deepcopy(data)
    candidate.pop('billing', None)
    if candidate.get('format') == BILLING_GLOBAL:
        candidate['format'] = GLOBAL
    candidate.setdefault('compositions', {})
    return candidate


def selection(value):
    legacy._fields(value, 'billing', (), ('reviewer', 'executor'))
    for role, name in value.items():
        if not isinstance(name, str) or not PROFILE_NAME.fullmatch(name):
            raise ValueError(tr('configuration.billing', field=f'billing.{role}'))
    return value


def billing_profiles(value, providers):
    """billing-profile-1: named descriptions of a billing case. Data only; unknown is the default."""
    if value is None:
        return {}
    legacy._fields(value, 'billing', (), ('profiles', 'defaults'))
    profiles = value.get('profiles', {})
    if not isinstance(profiles, dict) or len(profiles) > 32:
        raise ValueError(tr('configuration.billing', field='billing.profiles'))
    for name, profile in profiles.items():
        where = f'billing.profiles.{name}'
        if not PROFILE_NAME.fullmatch(name):
            raise ValueError(tr('configuration.billing', field=where))
        legacy._fields(profile, where, ('provider', 'platform', 'product', 'scheme', 'unit', 'basis', 'references'),
                       ('conditions',))
        for field in ('provider', 'platform', 'product', 'scheme', 'unit'):
            if not isinstance(profile[field], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', profile[field]):
                raise ValueError(tr('configuration.billing', field=f'{where}.{field}'))
        if profile['provider'] not in ('claude', 'codex') or profile['basis'] not in BASES:
            raise ValueError(tr('configuration.billing', field=where))
        if not isinstance(profile['references'], str) or not re.fullmatch(r'[a-f0-9]{64}', profile['references']):
            raise ValueError(tr('configuration.billing', field=f'{where}.references'))
        conditions = profile.get('conditions', {})
        if not isinstance(conditions, dict) or len(conditions) > 8:
            raise ValueError(tr('configuration.billing', field=f'{where}.conditions'))
        for condition, item in conditions.items():
            label = f'{where}.conditions.{condition}'
            legacy._fields(item, label, ('value', 'source'))
            if (not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', condition)
                    or not isinstance(item['value'], str) or not re.fullmatch(r'[a-z0-9_.-]{1,80}', item['value'])
                    or not isinstance(item['source'], str) or not item['source'].strip() or len(item['source']) > 500):
                raise ValueError(tr('configuration.billing', field=label))
    for role, name in selection(value.get('defaults', {})).items():
        if name not in profiles or profiles[name]['provider'] != providers.get(role):
            raise ValueError(tr('configuration.billing', field=f'billing.defaults.{role}'))
    return profiles
