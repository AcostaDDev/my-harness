"""Data-only profile proposals. No discovery, processes, configuration writes or activation."""
from copy import deepcopy

from my_harness.core.engine.chat import digest
from my_harness.core.engine.contracts import ContractError
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.definition import text_hash
from my_harness.core.engine.documents import Layout
from my_harness.i18n import tr
from my_harness.services import local_config
from my_harness.services.configuration import secretless, shape, PROFILE

CONTRACT = 'project-profile-proposal-1'


def invalid(key='invalid', **values):
    return ContractError(tr('profile_proposal.' + key, **values))


def executable_names(value):
    """Explain alias/path confusion without reflecting candidate values in diagnostics."""
    commands = []
    for kind in ('preparation', 'validations', 'allowed_command_prefixes'):
        items = value.get(kind)
        if not isinstance(items, list):
            continue  # The normal parser diagnoses malformed command tables.
        for index, item in enumerate(items):
            argv = item.get('argv') if isinstance(item, dict) else item
            commands.append((f'profile.{kind}[{index}]', argv))
    if 'formatter_argv' in value:
        commands.append(('profile.formatter_argv', value['formatter_argv']))
    for field, argv in commands:
        if (isinstance(argv, list) and argv and isinstance(argv[0], str)
                and not local_config.COMMAND_NAME.fullmatch(argv[0])):
            raise invalid('command_executable', field=field)


def text(value, limit=4000):
    if not isinstance(value, str) or not value.strip() or '\0' in value or len(value) > limit:
        raise invalid()


def documents(frozen, drafts):
    return {**{item['path']: item['sha256'] for item in frozen['drafts']},
            **{item['path']: text_hash(item['content']) for item in drafts}}


def validate(candidate, frozen, drafts, *, context=None):
    """The normal profile parser is reused, with deferred tools and exact source evidence per argv."""
    if candidate is None:
        return None
    try:
        if (not isinstance(candidate, dict)
                or set(candidate) - {'name', 'profile', 'tools', 'evidence', 'rationale', 'preparation_plan'}
                or not {'name', 'profile', 'tools', 'evidence', 'rationale'} <= set(candidate)):
            raise invalid()
        if len(freeze(candidate).encode('utf-8')) > local_config.MAX_BYTES:
            raise invalid()
        secretless(candidate)
        shape(candidate['profile'], PROFILE)
        text(candidate['rationale'])
        executable_names(candidate['profile'])
        profile = local_config._profile(candidate['name'], candidate['profile'], allow_formatter=True)
        if 'preparation_plan' in candidate:
            from my_harness.services.profile_preparation import validate_plan
            if context is None:
                raise invalid()
            validate_plan(candidate['preparation_plan'], profile, context)
        docs = documents(frozen, drafts)
        layout = frozen['project']['layout']
        target = Layout(layout['docs'], layout['state'], layout['next_steps'])
        if not {target.specification, target.architecture} <= docs.keys():
            raise invalid('context_required')
        sources = {entry['path']: entry['sha256'] for entry in frozen.get('inventory', {}).get('entries', [])
                   if entry['status'] == 'read' and entry['sha256']}
        sources.update(docs)
        commands = {('preparation', index): command.argv for index, command in enumerate(profile.preparation)}
        commands.update({('validation', index): command.argv for index, command in enumerate(profile.validations)})
        commands.update({('prefix', index): argv for index, argv in enumerate(profile.allowed_command_prefixes)})
        if profile.formatter_argv:
            commands['formatter', 0] = profile.formatter_argv
        tools = candidate['tools']
        if not isinstance(tools, list) or not 1 <= len(tools) <= 32:
            raise invalid('tools')
        names = set()
        for tool in tools:
            if not isinstance(tool, dict) or set(tool) != {'name', 'requirement'}:
                raise invalid('tools')
            text(tool['requirement'])
            name = tool['name']
            if not isinstance(name, str) or not local_config.COMMAND_NAME.fullmatch(name) or name in names:
                raise invalid('tools')
            names.add(name)
        if names != {argv[0] for argv in commands.values()}:
            raise invalid('tools')
        evidence = candidate['evidence']
        if not isinstance(evidence, list) or len(evidence) != len(commands) or len(evidence) > 64:
            raise invalid('evidence')
        seen = set()
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {'kind', 'index', 'purpose', 'sources', 'reason'}:
                raise invalid('evidence')
            if not isinstance(item['kind'], str) or type(item['index']) is not int:
                raise invalid('evidence')
            key = item['kind'], item['index']
            if key not in commands or key in seen:
                raise invalid('evidence')
            seen.add(key)
            text(item['reason'])
            if item['purpose'] not in {'test', 'build', 'check', 'prepare', 'format', 'execute'}:
                raise invalid('evidence')
            argv = commands[key]
            if key[0] == 'validation' and (item['purpose'] not in {'test', 'build', 'check'}
                    or len(argv) < 2 or argv[0] in {'echo', 'true', 'false', 'printf', 'sleep'}
                    or any(arg in {'--version', '-V', '--help', '-h', 'version', 'help'} for arg in argv[1:])):
                raise invalid('validation')
            refs = item['sources']
            if not isinstance(refs, list) or not 1 <= len(refs) <= 16:
                raise invalid('evidence')
            for ref in refs:
                if (not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}
                        or not isinstance(ref['path'], str) or sources.get(ref['path']) != ref['sha256']
                        or ref['sha256'] is None):
                    raise invalid('evidence')
        binding = {'documents': docs, 'head': frozen.get('head'), 'tree': frozen.get('tree'),
                   'inventory_sha256': frozen.get('inventory_sha256')}
        return {'contract': CONTRACT, 'candidate': deepcopy(candidate), 'binding': binding,
                'binding_sha256': digest(binding), 'tools_status': 'DEFERRED',
                'preparation_status': 'NOT_CHECKED', 'configuration_status': 'NOT_SAVED'}
    except ContractError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        # Do not echo untrusted commands, environment or candidate bodies in diagnostics.
        raise invalid() from None
