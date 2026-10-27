"""Structured reviewer output for documentary intakes; permissions remain proposals."""


def profile_schema():
    from my_harness.core.engine.prompts import TEXTS, _object
    command = _object({'argv': TEXTS, 'timeout_seconds': 'integer', 'cwd': 'string',
                       'environment': {'type': 'object', 'additionalProperties': {'type': 'string'}}},
                      ['argv', 'timeout_seconds'])
    validation = {**command, 'properties': {**command['properties'],
                  'junit': _object({'path': 'string', 'coverage': 'string'})}}
    profile = _object({'preparation': {'type': 'array', 'items': command},
                       'validations': {'type': 'array', 'minItems': 1, 'items': validation},
                       'allowed_command_prefixes': {'type': 'array', 'items': TEXTS},
                       'protected_paths': TEXTS, 'sensitive_paths': TEXTS, 'sensitive_allowlist': TEXTS,
                       'data_model_paths': TEXTS, 'executor_instructions': 'string',
                       'formatter_argv': TEXTS, 'formatter_paths': TEXTS},
                      ['preparation', 'validations', 'allowed_command_prefixes', 'protected_paths',
                       'sensitive_paths', 'data_model_paths', 'executor_instructions'])
    preparation = _object({'write_paths': TEXTS, 'local_paths': TEXTS, 'environment_paths': TEXTS,
        'network': TEXTS, 'scripts': 'boolean',
        'instructions': 'string',
        'executor_selection': _object({'model': 'string', 'effort': 'string', 'reason': 'string'}),
        'dependencies': {'type': 'array', 'items': _object({
            'name': 'string', 'version': 'string', 'lock_path': 'string', 'sha256': 'string'})}})
    return {**_object({'name': 'string', 'profile': profile, 'rationale': 'string', 'preparation_plan': preparation,
             'tools': {'type': 'array', 'minItems': 1, 'maxItems': 32,
                       'items': _object({'name': 'string', 'requirement': 'string'})},
             'evidence': {'type': 'array', 'maxItems': 64, 'items': _object({
                 'kind': {'type': 'string', 'enum': ['preparation', 'validation', 'formatter', 'prefix']},
                 'index': {'type': 'integer', 'minimum': 0},
                 'purpose': {'type': 'string', 'enum': ['test', 'build', 'check', 'prepare', 'format', 'execute']},
                 'sources': {'type': 'array', 'minItems': 1, 'maxItems': 16,
                             'items': _object({'path': 'string', 'sha256': 'string'})}, 'reason': 'string'})}},
            ['name', 'profile', 'rationale', 'tools', 'evidence']),
            'type': ['object', 'null']}
