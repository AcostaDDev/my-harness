"""P001-T003 (D255/D259): frozen billing binding of a native invocation.

Admission already freezes exact immutable configuration revisions (job `versions_json`, preparation plan,
assistance preview). This module only dereferences those revisions; it never consults the active or working
configuration, so a later save/activation cannot rebind queued work. Missing billing metadata is `unknown`.
"""
from pathlib import Path
import tomllib

from my_harness.services.configuration import BILLING_GLOBAL, BILLING_PROJECT, digest
from my_harness.storage.configuration_files import ConfigurationFiles
from my_harness.storage.models import ConfigurationScopeRow as Scope

FORMAT = 'billing-binding-1'


def document(session, scope, reference):
    """Exact immutable revision bytes, or None. The digest is checked; nothing is repaired or replaced."""
    head = session.get(Scope, scope)
    if head is None or not isinstance(reference, dict):
        return None
    try:
        files = ConfigurationFiles(Path(head.directory))
        raw = files.read(files.immutable(scope, int(reference['revision']), reference['sha256']))
        if raw is None or digest(raw) != reference['sha256']:
            return None
        return tomllib.loads(raw.decode('utf-8'))
    except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None


def resolve(session, agent, *, project=None, project_reference=None, global_reference=None):
    """`billing-binding-1` for one configured agent role, or None when no billing-capable format is frozen."""
    configuration = {'global': None, 'project': None}
    if project is None and project_reference is not None:
        configuration['project'] = {'scope': project_reference['scope'], 'revision': int(project_reference['revision']),
                                    'sha256': project_reference['sha256']}
        project = document(session, project_reference['scope'], project_reference)
        if project is None:
            return {'format': FORMAT, 'agent': agent, 'configuration': configuration, 'profile_name': None,
                    'profile': None, 'reason': 'configuration_unavailable'}
    if project is not None:
        global_reference = project.get('global')
    if global_reference is None:
        return None
    configuration['global'] = {'revision': int(global_reference['revision']), 'sha256': global_reference['sha256']}
    data = document(session, 'global', global_reference)
    if data is None:
        return {'format': FORMAT, 'agent': agent, 'configuration': configuration, 'profile_name': None,
                'profile': None, 'reason': 'configuration_unavailable'}
    selected = (project or {}).get('billing', {}) if (project or {}).get('format') == BILLING_PROJECT else {}
    billing = data.get('billing', {}) if data.get('format') == BILLING_GLOBAL else {}
    if not selected and not billing:
        return None
    name = selected.get(agent) or billing.get('defaults', {}).get(agent)
    profile = billing.get('profiles', {}).get(name) if name else None
    provider = ((project or data).get('agents') or {}).get(agent, {}).get('provider')
    reason = None
    if profile is None:
        reason = 'billing_profile_unknown'
    elif provider is not None and profile['provider'] != provider:
        profile, reason = None, 'billing_profile_unknown'
    if profile is not None:
        profile = {**{k: profile[k] for k in ('provider', 'platform', 'product', 'scheme', 'unit', 'basis',
                                              'references')},
                   # Profile conditions are operator assertions, never reported server evidence.
                   'conditions': {k: {'value': v['value'], 'provenance': 'asserted', 'source': v['source']}
                                  for k, v in sorted(profile.get('conditions', {}).items())}}
    return {'format': FORMAT, 'agent': agent, 'configuration': configuration, 'profile_name': name,
            'profile': profile, 'reason': reason}


def for_versions(session, versions, agent):
    """Managed jobs: the project revision sealed in `versions_json` at admission."""
    if not isinstance(versions, dict) or not versions.get('project_configuration_revision'):
        return None
    reference = {'scope': 'project:' + str(versions.get('project_registry_id')),
                 'revision': versions['project_configuration_revision'],
                 'sha256': versions.get('project_configuration_sha256')}
    return resolve(session, agent, project_reference=reference)
