"""Later edits: immutable documentary bindings and reuse of unchanged technical evidence."""
import copy
from pathlib import Path

from sqlalchemy import select

from my_harness.adapters.git import Git
from my_harness.adapters.preparation import file_hash, verify_files
from my_harness.core.engine.documents import layout
from my_harness.services.configuration import parse
from my_harness.services.configuration_setup import toml_document
from my_harness.storage.configuration import ConfigurationConflict, seal
from my_harness.storage.models import ProjectPreparationOperationRow as Preparation


def technical(data):
    return {key: data.get(key) for key in ('profile_name', 'profile', 'commands')}


def documentary(context, git):
    target = layout(context)
    paths = [target.agents, target.specification, target.architecture, target.decisions]
    return {'head': git.text('rev-parse', 'HEAD'),
            'documents': {path: file_hash(context.path(path)) for path in paths}}


def selected_receipt(session, scope, reference):
    from my_harness.storage.models import ConfigurationOperationRow as Operation
    row = session.scalar(select(Preparation).where(Preparation.project_id == scope[8:],
        Preparation.status == 'COMPLETED',
        Preparation.receipt['configuration']['sha256'].as_string() == reference['sha256'],
        Preparation.receipt['configuration']['revision'].as_integer() == reference['revision'])
        .order_by(Preparation.created_at.desc(), Preparation.id.desc()).limit(1))
    if row is None:
        for operation in session.scalars(select(Operation).where(Operation.kind == 'ACTIVATE',
                Operation.status == 'APPLIED').order_by(Operation.created_at.desc(), Operation.id.desc())):
            if any(ref['scope'] == scope and ref['sha256'] == reference['sha256']
                   and ref['revision'] == reference['revision'] for ref in operation.payload['references']):
                return session.get(Preparation, operation.payload['evidence'][scope]['operation_id'])
    return row


def prepared(session, scope, data, *, reference, verify=True):
    """Use exact evidence or the receipt selected by an activation, never the newest similar receipt."""
    from my_harness.services.profile_preparation import verify_profile_receipt
    from my_harness.storage.models import ConfigurationScopeRow as Scope, ConfigurationRevisionRow as Revision
    row = selected_receipt(session, scope, reference)
    if row is None:
        # A derived candidate may reuse only the currently active authority's evidence.
        head = session.get(Scope, scope)
        if head and head.active_revision and head.active_revision != reference['revision']:
            active = session.get(Revision, (scope, head.active_revision))
            row = selected_receipt(session, scope, {'revision': active.revision, 'sha256': active.sha256})
    if (not row or not row.receipt or row.plan.get('contract') != 'project-profile-preparation-1'
            or technical(row.plan['configuration_data']) != technical(data)
            or data.get('edit', {}).get('preparation_plan', row.plan['technical']) != row.plan['technical']):
        raise ConfigurationConflict('project_preparation_required')
    if verify:
        verify_profile_receipt(Path(data['project']['root']), row.receipt)
    return row


def verify_revision(session, scope, data, repository):
    """Also usable at startup, before runtime projects/ports have been installed."""
    state = repository._state(session, repository._files(session), scope)
    row = prepared(session, scope, data, reference=state['saved'])
    old = (parse(repository.document(scope, state['active']['revision']), scope) if state['active'] else None)
    # Reuse is limited to agent/policy/global changes. Technical edits require their own exact preparation.
    reuse = (old is not None and technical(old) == technical(data)
             and prepared(session, scope, old, reference=state['active'], verify=False).id == row.id)
    from my_harness.storage.models import ConfigurationRevisionRow as Revision
    global_revision = session.get(Revision, ('global', data['global']['revision']))
    if not global_revision or global_revision.sha256 != data['global']['sha256']:
        raise ConfigurationConflict('project_global_reference_changed')
    global_data = parse(repository.document('global', global_revision.revision), 'global')
    git = Git(Path(data['project']['root']), executable=global_data['git']['executable'])
    if git.run('status', '--porcelain=v1', '--untracked-files=all').strip():
        raise ConfigurationConflict('prepared_head_changed')
    if not reuse and git.text('rev-parse', 'HEAD') != row.receipt['commit']:
        raise ConfigurationConflict('prepared_head_changed')
    if data.get('edit'):
        verify_files(Path(data['project']['root']), data['edit']['documents'])
    return {'operation_id': row.id, 'receipt_sha256': seal(row.receipt), 'commit': row.receipt['commit']}


def derive_global(repository, change):
    """A reviewed global save includes exact private copies, never mutable catalog references."""
    from sqlalchemy.orm import Session
    from my_harness.storage.models import ConfigurationScopeRow as Scope
    changes = [change]
    if not change['validated']:
        return changes
    global_state = repository.read('global')
    reference = {'revision': (global_state['saved']['revision'] + 1 if global_state['saved'] else 1),
                 'sha256': seal_text(change['text'])}
    with Session(repository.managed.engine) as session:
        scopes = list(session.scalars(select(Scope.scope).where(Scope.scope != 'global',
            Scope.active_revision.is_not(None)).order_by(Scope.scope)))
    for scope in scopes:
        state = repository.read(scope)
        active_data = parse(repository.document(scope, state['active']['revision']), scope)
        derived = False
        if state['saved'] != state['active'] and state['saved']:
            from my_harness.storage.models import ConfigurationRevisionRow as Revision, ConfigurationOperationRow as Operation
            with Session(repository.managed.engine) as session:
                revision = session.get(Revision, (scope, state['saved']['revision']))
                operation = session.get(Operation, revision.operation_id)
                saved_data = parse(repository.document(scope, state['saved']['revision']), scope, validated=False)
                derived = (any(c['scope'] == 'global' for c in operation.payload.get('changes', []))
                    and {k: v for k, v in saved_data.items() if k != 'global'}
                    == {k: v for k, v in active_data.items() if k != 'global'})
        if state['status'] != 'READY' or state['saved'] != state['active'] and not derived:
            raise ConfigurationConflict('project_has_saved_configuration_changes')
        data = copy.deepcopy(active_data)
        data['global'] = reference
        changes.append({'scope': scope, 'text': toml_document(data), 'validated': True,
            'expected_version': state['version'], 'base_sha256': state['actual_sha256'],
            'active_sha256': state['active']['sha256'], 'import_external': False})
    return changes


def seal_text(text):
    from my_harness.services.configuration import digest
    return digest(text.encode())


def impact(session, repository, changes):
    from my_harness.storage.models import ManagedRunRow as Run, ManagedJobRow as Job, RegisteredProjectRow as Project
    roots = list(session.scalars(select(Project.root))) if any(c['scope'] == 'global' for c in changes) else [
        session.get(Project, c['scope'][8:]).root for c in changes]
    jobs = [{'id': row.id, 'run_id': row.run_id, 'status': row.status}
            for row in session.scalars(select(Job).join(Run, Job.run_id == Run.id).where(
                Run.root.in_(roots), Job.status.in_(('QUEUED', 'ACTIVE', 'RECOVERY_REQUIRED'))).order_by(Job.id))]
    projects = []
    for change in changes:
        if change['scope'] == 'global':
            continue
        state = repository.read(change['scope'])
        old = parse(repository.document(change['scope'], state['active']['revision']), change['scope']) if state['active'] else None
        new = parse(change['text'], change['scope'], validated=False)
        plan_changed = False
        if old and new.get('edit'):
            row = prepared(session, change['scope'], old, reference=state['active'], verify=False)
            plan_changed = new['edit']['preparation_plan'] != row.plan['technical']
        projects.append({'scope': change['scope'], 'profile': new.get('profile_name'),
            'commands': new.get('profile', {}).get('validations', []), 'tools': new.get('commands', {}).get('executables', {}),
            'preparation_required': not old or technical(old) != technical(new) or plan_changed,
            'shared_catalog_followed': False})
    return {'restart_required': any(c['scope'] == 'global' for c in changes), 'projects': projects,
            'jobs': jobs, 'admitted_jobs_keep_frozen_configuration': True, 'activation_rejects_pending_work': True}


def billing_review(session, changes):
    """D263: refuse at save what would only surface later as `billing_profile_unknown`; report inherited defaults.

    Refused: a global profile whose pinned bundle is not available, and an explicit `project-config-2` selection
    that its referenced global revision (or the global candidate of the same save) lacks or whose provider differs
    from the project's agent. A derived copy carries its project's selection, so removing or re-providing a selected
    profile is refused naming that project. Inherited defaults keep `project-config-1` meaning and are only reported.
    """
    from my_harness.services.configuration import BILLING_GLOBAL, BILLING_PROJECT, digest
    from my_harness.storage import accounting
    from my_harness.storage.billing import choose, document
    candidates, refusals, unknown = {}, [], []
    for change in changes:
        if change['scope'] != 'global' or not change['validated']:
            continue
        data = parse(change['text'], 'global')
        candidates[digest(change['text'].encode())] = data
        if data['format'] in (BILLING_GLOBAL, 'local-config-11'):
            for name, profile in sorted(data.get('billing', {}).get('profiles', {}).items()):
                if not accounting.available(session, profile['references']):
                    refusals.append({'setting': f'billing.profiles.{name}.references', 'code': 'reference_unavailable'})
    for change in sorted(changes, key=lambda item: item['scope']):
        scope = change['scope']
        if scope == 'global' or not change['validated']:
            continue
        data = parse(change['text'], scope)
        global_data = candidates.get(data['global']['sha256']) or document(session, 'global', data['global'])
        selected = data.get('billing', {}) if data['format'] in (BILLING_PROJECT, 'project-config-3') else {}
        for role in ('reviewer', 'executor'):
            chosen = choose(data, global_data, role) if global_data is not None else None
            if selected.get(role):
                if chosen is None or chosen[1] is None:
                    profiles = ((global_data or {}).get('billing', {}).get('profiles', {})
                                if (global_data or {}).get('format') in (BILLING_GLOBAL, 'local-config-11') else {})
                    refusals.append({'project': scope[8:], 'role': role, 'setting': f'billing.{role}',
                                     'code': ('billing_provider_mismatch' if selected[role] in profiles
                                              else 'billing_profile_missing')})
            elif chosen is not None and chosen[1] is None:
                unknown.append({'scope': scope, 'role': role, 'profile': chosen[0], 'reason': 'billing_profile_unknown'})
    return refusals, unknown
