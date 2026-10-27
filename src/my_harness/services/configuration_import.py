"""Explicit legacy TOML conversion. Import saves drafts, never historical authority/receipts."""
import copy
from pathlib import Path
import tomllib

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.services import local_config as legacy
from my_harness.services.configuration import digest, parse
from my_harness.services.configuration_setup import toml_document
from my_harness.storage.configuration import ConfigurationConflict, seal
from my_harness.storage.models import (ConfigurationScopeRow as Scope,
    ConfigurationOperationRow as Operation, RegisteredProjectRow as Project, RegisteredProjectEventRow as Event)
from my_harness.storage.backup import _read


def imported(session):
    """The first sealed import remains provenance, even after later edits."""
    for row in session.scalars(select(Operation).where(Operation.kind == 'SAVE').order_by(Operation.created_at, Operation.id)):
        if row.payload.get('legacy_import'):
            return row.payload['legacy_import']
    return None


def command(value):
    return {'argv': list(value.argv), 'cwd': value.cwd, 'environment': dict(value.environment),
            'timeout_seconds': value.timeout_seconds}


def profile(value):
    result = {key: list(getattr(value, key)) for key in
              ('protected_paths', 'sensitive_paths', 'sensitive_allowlist', 'data_model_paths')}
    result.update(preparation=[command(c) for c in value.preparation],
                  validations=[command(c) for c in value.validations],
                  allowed_command_prefixes=[list(c) for c in value.allowed_command_prefixes],
                  executor_instructions=value.executor_instructions)
    for declaration in value.junit_reports:
        result['validations'][value.validations.index(declaration.command)]['junit'] = {
            'path': declaration.path, 'coverage': declaration.coverage}
    if value.formatter_argv:
        result.update(formatter_argv=list(value.formatter_argv), formatter_paths=list(value.formatter_paths))
    return result


def agents(declarations, policy):
    result = {}
    for role, cli in declarations.items():
        item = {'provider': cli.provider, 'environment': dict(cli.environment), 'timeout_seconds': cli.timeout_seconds}
        if cli.executable:
            item['executable'] = list(cli.executable)
        if cli.cli_version:
            item['cli_version'] = cli.cli_version
        if role == 'executor' and cli.provider == 'claude':
            item.update({key: list(getattr(cli, key)) for key in legacy.TOOL_KEYS})
        result[role] = item
    result['reviewer'].update(model=policy.reviewer_model, effort=policy.reviewer_effort)
    return result


def policy(value):
    return {key: list(getattr(value, key)) if key in ('executor_models', 'executor_efforts') else getattr(value, key)
            for key in ('planning_mode', 'executor_mode', 'executor_models', 'executor_efforts', 'max_revision_cycles')}


class ConfigurationImport:
    def __init__(self, runtime):
        self.runtime = runtime
        self.setup = runtime.setup
        self.repository = self.setup.repository

    def preview(self, source, reason, *, session=None):
        self.repository._writable()
        if not self.setup.legacy:
            raise ConfigurationConflict('configuration_legacy_source_required')
        selected = self.setup.source
        if selected is None or Path(source) != selected:
            raise ConfigurationConflict('configuration_source_conflict')
        # The original reader's permissions remain unchanged. The bounded raw read adds no chmod or writes.
        legacy._read(selected)
        raw = _read(selected, legacy.MAX_BYTES)
        data = tomllib.loads(raw.decode())
        config = legacy.build(data, selected)
        if session is None:
            with Session(self.runtime.engine) as read:
                return self._preview(read, source, reason, data, config, raw)
        return self._preview(session, source, reason, data, config, raw)

    def _preview(self, session, source, reason, data, config, raw):
        if session.scalar(select(Scope.scope).limit(1)):
            raise ConfigurationConflict('configuration_already_imported')
        composer = config.registrar
        records = list(session.scalars(select(Project).order_by(Project.id)))
        registry = [{'id': p.id, 'root': p.root, 'version': p.version, 'status': p.status,
                     'row_sha256': p.row_sha256} for p in records]
        projects = {p.id: p for p in config.projects}
        rows = {item['id']: copy.deepcopy(item) for item in data.get('projects', [])}
        for row in records:
            if row.status != 'ACTIVE':
                if row.id in projects or any(row.root == str(p.context.root) for p in projects.values()):
                    raise ConfigurationConflict('configuration_project_conflict')
                continue
            if row.id in projects or any(row.root == str(p.context.root) for p in projects.values()):
                raise ConfigurationConflict('configuration_project_conflict')
            composed = composer.compose(row.row, 'configuration import', registry=(row.version, row.row_sha256))
            projects[row.id] = composer.install(composed)
            rows[row.id] = copy.deepcopy(row.row)
        roots = [p.context.root for p in projects.values()]
        if any(root.is_relative_to(self.setup.directory) or self.setup.directory.is_relative_to(root) for root in roots):
            raise ConfigurationConflict('configuration_overlaps_checkout')
        if any(a != b and (a.is_relative_to(b) or b.is_relative_to(a)) for a in roots for b in roots):
            raise ConfigurationConflict('configuration_project_conflict')
        # Conversion freezes the effective defaults/presets, not whichever catalog has that name later.
        global_data = {key: copy.deepcopy(value) for key, value in data.items() if key not in ('projects', 'providers')}
        global_data['format'] = 'local-config-9'
        global_data.setdefault('registration', {'roots': [], 'bootstrap_enabled': False})
        if data['format'] == 'local-config-1':
            first = next(iter(projects.values()))
            global_data['agents'] = agents(composer.agents, first.context.policy)
        text = toml_document(global_data)
        parse(text, 'global')
        reference = {'revision': 1, 'sha256': digest(text.encode())}
        changes = [{'scope': 'global', 'text': text, 'validated': True, 'expected_version': 0,
                    'base_sha256': None, 'active_sha256': None, 'import_external': False}]
        imported_projects = []
        for identifier, project in sorted(projects.items()):
            row = rows[identifier]
            if project.permission_authority is not None:
                raise ConfigurationConflict('configuration_permission_authority_requires_resolution')
            commands = copy.deepcopy(composer.compositions[row['composition']][1] if composer.registrable else row['commands'])
            owned = {'format': 'project-config-1', 'project': {'id': identifier, 'root': str(project.context.root)},
                     'global': reference, 'profile_name': 'imported-' + identifier,
                     'profile': profile(project.context.profile), 'commands': commands,
                     'policy': policy(project.context.policy),
                     'agents': agents(composer._live[project.context.root][4], project.context.policy),
                     'provenance': {'source': 'legacy-configuration', 'sha256': digest(raw)}}
            changes.append({'scope': 'project:' + identifier, 'text': toml_document(owned), 'validated': False,
                'expected_version': 0, 'base_sha256': None, 'active_sha256': None, 'import_external': False})
            imported_projects.append({'id': identifier, 'root': str(project.context.root), 'row': row,
                'versions': dict(project.versions), 'work_language': project.context.work_language})
        snapshot = {'source': str(source), 'sha256': digest(raw), 'format': data['format'],
                    'registry': registry, 'projects': imported_projects}
        preview = self.repository._preview(session, self.repository._files(session), changes, reason)
        preview.pop('sha256')
        preview['legacy_import'] = snapshot
        return {**preview, 'sha256': seal(preview)}

    def save(self, source, reason, preview_sha256, key):
        request = {'kind': 'IMPORT', 'source': source, 'reason': reason, 'preview_sha256': preview_sha256}
        with Session(self.runtime.engine) as session:
            replay = self.repository._replay(session, key, request)
            if replay:
                return replay
        return self.repository._save([], reason=reason, preview_sha256=preview_sha256, key=key, request=request,
            preview_factory=lambda session, files: self.preview(source, reason, session=session))


def materialize(session, operation, now):
    snapshot = operation.payload.get('legacy_import')
    if not snapshot:
        return
    current = [{'id': p.id, 'root': p.root, 'version': p.version, 'status': p.status, 'row_sha256': p.row_sha256}
               for p in session.scalars(select(Project).order_by(Project.id))]
    if current != snapshot['registry']:
        raise ConfigurationConflict('configuration_import_registry_changed')
    for item in snapshot['projects']:
        if session.get(Project, item['id']):
            continue
        row = Project(id=item['id'], root=item['root'], version=1, status='ACTIVE',
            composition=item['row'].get('composition'), profile=item['row'].get('profile'), row=item['row'],
            row_sha256=seal(item['row']), trust={'source': 'configuration-import', 'sha256': snapshot['sha256']},
            created_at=now, updated_at=now)
        session.add(row)
        session.flush()
        session.add(Event(project_id=row.id, version=1, action='configuration_import', row=row.row,
            row_sha256=row.row_sha256, previous_sha256=None, preview_sha256=operation.payload['sha256'],
            actor=operation.payload['actor'], reason=operation.payload['reason'], recorded_at=now))


def promote_registry(session, repository, references, now):
    snapshot = imported(session)
    if not snapshot or session.get(Scope, 'global').active_revision is not None:
        return
    for item in snapshot['projects']:
        scope = 'project:' + item['id']
        if scope not in {ref['scope'] for ref in references}:
            raise ConfigurationConflict('configuration_import_requires_all_projects')
        head = session.get(Scope, scope)
        row = session.get(Project, item['id'])
        reference = next(ref for ref in references if ref['scope'] == scope)
        data = parse(repository.document(scope, reference['revision']), scope)
        before = row.row_sha256
        row.row = {key: value for key, value in row.row.items() if key not in ('composition', 'profile', 'commands', 'work_language')}
        row.row = {**row.row, 'composition': None, 'policy': data['policy']}
        row.composition, row.profile = None, None
        row.version += 1
        row.row_sha256, row.updated_at = seal(row.row), now
        session.add(Event(project_id=row.id, version=row.version, action='configuration_activate', row=row.row,
            row_sha256=row.row_sha256, previous_sha256=before, preview_sha256=seal(references),
            actor={}, reason='Activate explicitly prepared imported profile', recorded_at=now))


def verify_registry(session, snapshot):
    expected = {item['id']: (item['root'], item['version'], item['row_sha256'], item['status'])
                for item in snapshot['registry']}
    for item in snapshot['projects']:
        expected.setdefault(item['id'], (item['root'], 1, seal(item['row']), 'ACTIVE'))
    actual = {row.id: (row.root, row.version, row.row_sha256, row.status)
              for row in session.scalars(select(Project))}
    if actual != expected:
        raise ConfigurationConflict('configuration_import_registry_changed')
