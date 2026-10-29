"""Versioned configuration journal and activation primitives (P013-T004, D221).

No API, clients or runtime consumers are installed here. Callers supply an explicit
configuration directory/state directory and a trusted project preparation verifier.
Every mutation shares the managed SQLite barrier; a file lock spans intent commits.
"""
import difflib
import os
from pathlib import Path
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.i18n import tr
from my_harness.core.engine.contracts import freeze
from my_harness.services.configuration import digest, parse
from my_harness.services.managed_runtime import PROJECT_ID
from my_harness.storage.backup import is_read_only_archive
from my_harness.storage.configuration_files import ConfigurationFiles
from my_harness.storage.managed import Conflict
from my_harness.storage.models import (
    ConfigurationOperationRow as Operation, ConfigurationRevisionRow as Revision,
    ConfigurationScopeRow as Scope, RegisteredProjectRow as Project, ManagedRunRow as Run,
)
from my_harness.storage.permissions import actor
from my_harness.storage.registry import ProjectRegistryRepository

FORMAT = 'configuration-operation-1'
UNRESOLVED = ('INTENDED', 'FILES_WRITTEN', 'RECOVERY_REQUIRED', 'CONFLICT')


class ConfigurationConflict(Conflict):
    def __init__(self, code, details=None):
        self.code = code
        # Structured, path-free corrections (project, role, code, setting) for the protected editor.
        self.details = details
        super().__init__(code)


def seal(value):
    return digest(freeze(value).encode())


def scope_name(value):
    if (value != 'global' and (not isinstance(value, str) or not value.startswith('project:')
                              or not PROJECT_ID.fullmatch(value[8:]))):
        raise ValueError(tr('configuration.scope'))
    return value


def live(activation):
    """D238: an ACTIVATE operation applied by the running service at an idle boundary."""
    return bool(activation and activation.kind == 'ACTIVATE' and activation.payload.get('apply') == 'live')


def removed_fields(before, after, prefix=''):
    """Leaves present in the saved document and absent from the candidate: an explicit removal."""
    removed = []
    for key, value in before.items():
        path = f'{prefix}{key}'
        if key not in after:
            removed.append(path)
        elif isinstance(value, dict) and isinstance(after[key], dict):
            removed += removed_fields(value, after[key], path + '.')
    return removed


def operation_view(row):
    result = row.result
    if row.kind == 'ASSIST':
        process = row.payload.get('process')
        result = {**(result or {}), 'journal': {
            'owner': row.payload['owner'], 'owner_closed': row.payload.get('owner_closed', False),
            'process': ({key: process.get(key) for key in ('identity', 'status', 'capture')} if process else None)}}
    return {'id': row.id, 'format': row.format, 'kind': row.kind, 'status': row.status,
            'result': result, 'created_at': row.created_at, 'updated_at': row.updated_at}


class ConfigurationRepository:
    def __init__(self, managed, directory, *, state_dir, project_verifier=None, checkpoint=None):
        self.managed = managed
        self.directory, self.state_dir = Path(directory), Path(state_dir)
        # The verifier belongs to the service, never to a request or an AI candidate.
        # T008/T009 will provide preparation/HEAD binding and runtime recomposition.
        self.project_verifier = project_verifier
        self.derive_projects = False
        self.checkpoint = checkpoint or (lambda stage: None)
        # D238: the running service classifies restart-only fields and stages live candidates.
        # Without them (storage-only callers) a global activation keeps the D222 restart path.
        self.restart_fields = None
        self.live_verifier = None

    def _writable(self):
        if is_read_only_archive(self.managed.engine):
            raise ConfigurationConflict('read_only_archive')

    def _files(self, session):
        files = ConfigurationFiles(self.directory)
        roots = set(session.scalars(select(Project.root))) | set(session.scalars(select(Run.root)))
        for path in (files.root, *files.root.parents):
            if os.path.lexists(path / '.git'):
                raise ConfigurationConflict('configuration_inside_checkout')
        if any(files.root.is_relative_to(Path(root)) or Path(root).is_relative_to(files.root) for root in roots):
            raise ConfigurationConflict('configuration_overlaps_checkout')
        for row in session.scalars(select(Scope)):
            if row.directory != str(files.root):
                raise ConfigurationConflict('configuration_directory_changed')
        for row in session.scalars(select(Operation).where(Operation.kind == 'SAVE')):
            if row.format != FORMAT:
                raise ConfigurationConflict('unknown_configuration_operation_format')
            if row.payload['directory'] != str(files.root) or row.payload['state_dir'] != str(self.state_dir):
                raise ConfigurationConflict('configuration_directory_changed')
        return files

    @staticmethod
    def _ref(session, scope, revision):
        if revision is None:
            return None
        row = session.get(Revision, (scope, revision))
        if row is None:
            raise ConfigurationConflict('missing_configuration_revision')
        return {'scope': scope, 'revision': revision, 'sha256': row.sha256, 'status': row.status}

    def _state(self, session, files, scope):
        row = session.get(Scope, scope)
        actual = files.hash(files.working(scope))
        result = {'scope': scope, 'version': row.version if row else 0,
                  'saved': self._ref(session, scope, row.saved_revision) if row else None,
                  'active': self._ref(session, scope, row.active_revision) if row else None,
                  'pending': self._ref(session, scope, row.pending_revision) if row else None,
                  'working_sha256': row.working_sha256 if row else None, 'actual_sha256': actual}
        result['status'] = 'UNCONFIGURED' if not row or not row.active_revision else 'READY'
        if row and row.pending_revision:
            pending = session.get(Operation, row.pending_operation_id) if row.pending_operation_id else None
            result['status'] = 'APPLY_PENDING' if live(pending) else 'RESTART_REQUIRED'
        if actual != result['working_sha256']:
            result['status'] = 'EXTERNAL_CHANGE'
        for ref in (result['saved'], result['active'], result['pending']):
            if ref and files.hash(files.immutable(scope, ref['revision'], ref['sha256'])) != ref['sha256']:
                result['status'] = 'INVALID'
        if any(ref and ref['status'] != 'VALIDATED' for ref in (result['active'], result['pending'])):
            result['status'] = 'INVALID'
        if session.scalar(select(Operation.id).where(Operation.status.in_(UNRESOLVED),
                (Operation.kind != 'ASSIST') | (Operation.status == 'RECOVERY_REQUIRED')).limit(1)):
            result['status'] = 'RECOVERY_REQUIRED'
        return result

    def read(self, scope='global'):
        scope_name(scope)
        if is_read_only_archive(self.managed.engine):
            # No access to original paths in a restored database.
            with Session(self.managed.engine) as session:
                row = session.get(Scope, scope)
                return {'scope': scope, 'version': row.version if row else 0, 'status': 'READ_ONLY_ARCHIVE',
                        'saved': self._ref(session, scope, row.saved_revision) if row else None,
                        'active': self._ref(session, scope, row.active_revision) if row else None,
                        'pending': self._ref(session, scope, row.pending_revision) if row else None}
        with Session(self.managed.engine) as session:
            return self._state(session, self._files(session), scope)

    def document(self, scope, revision):
        """Authenticated-editor primitive. Never substitute the journal or working copy."""
        scope_name(scope)
        archive = is_read_only_archive(self.managed.engine)
        with Session(self.managed.engine) as session:
            files = None if archive else self._files(session)
            ref = self._ref(session, scope, revision)
            if ref is None:
                raise LookupError(tr('configuration.revision_unknown'))
            if archive:
                from my_harness.storage.backup import restored_artifact, _read
                head = session.get(Scope, scope)
                source = Path(head.directory).joinpath(*ConfigurationFiles.immutable(scope, revision, ref['sha256']))
                path = restored_artifact(self.managed.engine, source)
                raw = _read(path, 65536) if path else None
            else:
                raw = files.read(files.immutable(scope, revision, ref['sha256']))
            if raw is None or digest(raw) != ref['sha256']:
                raise ConfigurationConflict('immutable_configuration_changed')
            return raw.decode('utf-8')

    def operation(self, operation_id):
        with Session(self.managed.engine) as session:
            row = session.get(Operation, operation_id)
            if row is None:
                raise LookupError(tr('configuration.operation_unknown'))
            return operation_view(row)

    @staticmethod
    def _clear(session):
        if session.scalar(select(Operation.id).where(Operation.status.in_(UNRESOLVED)).limit(1)):
            raise ConfigurationConflict('configuration_recovery_required')

    def _candidate(self, session, change):
        if set(change) != {'scope', 'text', 'validated', 'expected_version', 'base_sha256', 'active_sha256',
                           'import_external'}:
            raise ValueError(tr('configuration.change'))
        scope = scope_name(change['scope'])
        if type(change['validated']) is not bool or type(change['import_external']) is not bool:
            raise ValueError(tr('configuration.boolean'))
        if type(change['expected_version']) is not int or change['expected_version'] < 0:
            raise ValueError(tr('configuration.expected_version'))
        data = parse(change['text'], scope, validated=change['validated'])
        if change['validated']:
            if scope == 'global':
                if Path(data['service']['state_dir']) != self.state_dir:
                    raise ConfigurationConflict('state_directory_fixed_at_startup')
            else:
                project = session.get(Project, scope[8:])
                if not project or project.status != 'ACTIVE' or project.root != data['project']['root']:
                    raise ConfigurationConflict('project_identity_changed')
        return data

    def _preview(self, session, files, changes, reason):
        self._clear(session)
        if self.derive_projects and len(changes) == 1 and changes[0]['scope'] == 'global':
            from my_harness.services.configuration_editing import derive_global
            changes = derive_global(self, changes[0])
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ValueError(tr('configuration.reason'))
        if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
            raise ValueError(tr('configuration.changes'))
        result, seen = [], set()
        for change in sorted(changes, key=lambda item: item['scope']):
            self._candidate(session, change)
            scope = change['scope']
            if scope in seen:
                raise ValueError(tr('configuration.scope_duplicate'))
            seen.add(scope)
            state = self._state(session, files, scope)
            if (state['status'] in ('INVALID', 'RECOVERY_REQUIRED')
                    or (state['pending'] and change['validated'])):
                raise ConfigurationConflict(state['status'].lower())
            if (state['version'] != change['expected_version'] or state['actual_sha256'] != change['base_sha256']
                    or (state['active']['sha256'] if state['active'] else None) != change['active_sha256']):
                raise ConfigurationConflict('stale_configuration_preview')
            if state['status'] == 'EXTERNAL_CHANGE' and not change['import_external']:
                raise ConfigurationConflict('external_configuration_change')
            revision = state['saved']['revision'] + 1 if state['saved'] else 1
            before = files.read(files.working(scope))
            diff = ''.join(difflib.unified_diff((before or b'').decode('utf-8', errors='replace').splitlines(True),
                                               change['text'].splitlines(True), fromfile='saved', tofile='candidate'))
            try:
                removed = removed_fields(parse(before.decode(), scope, validated=False),
                                         parse(change['text'], scope, validated=False)) if before else []
            except (ValueError, UnicodeDecodeError):
                removed = []
            result.append({**change, 'revision': revision, 'sha256': digest(change['text'].encode()),
                           'status': 'VALIDATED' if change['validated'] else 'DRAFT', 'diff': diff,
                           'removed_fields': removed})
        from my_harness.services.configuration_editing import billing_review
        refusals, unknown = billing_review(session, changes)
        if refusals:
            raise ConfigurationConflict('billing_configuration_refused', refusals)
        preview = {'format': FORMAT, 'kind': 'SAVE', 'changes': result, 'reason': reason,
                   'impact': sorted(seen), 'directory': str(files.root), 'state_dir': str(self.state_dir)}
        if self.derive_projects or any(item['scope'].startswith('project:') for item in changes):
            from my_harness.services.configuration_editing import impact
            preview['effects'] = impact(session, self, changes)
            if unknown:
                # D263: roles whose inherited global default would resolve as unknown; reported, not refused.
                preview['effects']['billing_unknown'] = unknown
        return {**preview, 'sha256': seal(preview)}

    def preview(self, changes, *, reason):
        self._writable()
        with Session(self.managed.engine) as session:
            return self._preview(session, self._files(session), changes, reason)

    @staticmethod
    def _replay(session, key, request):
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise ValueError(tr('configuration.key'))
        previous = session.scalar(select(Operation).where(Operation.idempotency_key == key))
        if previous and previous.request_sha256 != seal(request):
            raise ConfigurationConflict('configuration_key_reused')
        return operation_view(previous) if previous else None

    def _operation(self, session, key, request, payload, *, kind, status):
        now = self.managed._now()
        row = Operation(id=str(uuid.uuid4()), format=FORMAT, kind=kind, status=status, idempotency_key=key,
                        request_sha256=seal(request), payload={**payload, 'actor': actor()},
                        created_at=now, updated_at=now)
        session.add(row)
        session.flush()
        return row

    def save(self, changes, *, reason, preview_sha256, key):
        self._writable()
        request = {'kind': 'SAVE', 'changes': changes, 'reason': reason, 'preview_sha256': preview_sha256}
        return self._save(changes, reason=reason, preview_sha256=preview_sha256, key=key, request=request)

    def _save(self, changes, *, reason, preview_sha256, key, request, preview_factory=None):
        with Session(self.managed.engine) as session:
            replay = self._replay(session, key, request)
            if replay:
                return replay
            files = self._files(session)
        with files.locked():
            with self.managed._write() as session:
                replay = self._replay(session, key, request)
                if replay:
                    return replay
                preview = (preview_factory(session, self._files(session)) if preview_factory else
                           self._preview(session, self._files(session), changes, reason))
                if preview['sha256'] != preview_sha256:
                    raise ConfigurationConflict('stale_configuration_preview')
                row = self._operation(session, key, request, preview, kind='SAVE', status='INTENDED')
                operation_id = row.id
            self.checkpoint('intended')
            return self._complete(operation_id, files)

    def _complete(self, operation_id, files):
        try:
            with self.managed._write() as session:
                self._files(session)
                row = session.get(Operation, operation_id)
                for change in row.payload['changes']:
                    scope, raw = change['scope'], change['text'].encode()
                    head = session.get(Scope, scope)
                    if (head.version if head else 0) != change['expected_version']:
                        raise ConfigurationConflict('stale_configuration_intent')
                    files.publish(files.immutable(scope, change['revision'], change['sha256']), raw, None, immutable=True)
                    self.checkpoint('immutable_written')
                    files.publish(files.working(scope), raw, change['base_sha256'])
                    self.checkpoint('working_written')
                row.status, row.updated_at = 'FILES_WRITTEN', self.managed._now()
            self.checkpoint('files_written')
            with self.managed._write() as session:
                row = session.get(Operation, operation_id)
                self._files(session)
                refs = []
                for change in row.payload['changes']:
                    scope = change['scope']
                    if (files.hash(files.working(scope)) != change['sha256'] or files.hash(
                            files.immutable(scope, change['revision'], change['sha256'])) != change['sha256']):
                        raise ConfigurationConflict('configuration_publication_changed')
                    head = session.get(Scope, scope)
                    if (head.version if head else 0) != change['expected_version']:
                        raise ConfigurationConflict('stale_configuration_intent')
                    if head is None:
                        head = Scope(scope=scope, directory=str(files.root), version=0, updated_at=self.managed._now())
                        session.add(head)
                        session.flush()
                    head.version += 1
                    head.saved_revision, head.working_sha256 = change['revision'], change['sha256']
                    head.updated_at = self.managed._now()
                    session.add(Revision(scope=scope, revision=change['revision'], sha256=change['sha256'],
                                         status=change['status'], operation_id=row.id, created_at=head.updated_at))
                    refs.append({'scope': scope, 'revision': change['revision'], 'sha256': change['sha256'],
                                 'version': head.version})
                from my_harness.services.configuration_import import materialize
                materialize(session, row, self.managed._now())
                row.status, row.updated_at, row.result = 'SAVED', self.managed._now(), {'references': refs}
                self.checkpoint('before_final_commit')
                return operation_view(row)
        except Exception:
            with self.managed._write() as session:
                row = session.get(Operation, operation_id)
                if row.status == 'SAVED':
                    # A commit may have completed before its acknowledgement failed.
                    # Never demote that durable result into an unrecoverable stale intent.
                    return operation_view(row)
                row.status, row.updated_at = 'RECOVERY_REQUIRED', self.managed._now()
            raise

    def recovery_preview(self, operation_id):
        self._writable()
        with Session(self.managed.engine) as session:
            files = self._files(session)
            row = session.get(Operation, operation_id)
            if not row or row.kind != 'SAVE' or row.status not in UNRESOLVED:
                raise ConfigurationConflict('configuration_not_recoverable')
            observed = []
            for change in row.payload['changes']:
                working = files.hash(files.working(change['scope']))
                immutable = files.hash(files.immutable(change['scope'], change['revision'], change['sha256']))
                if working not in (change['base_sha256'], change['sha256']) or immutable not in (None, change['sha256']):
                    raise ConfigurationConflict('unknown_configuration_bytes')
                observed.append({'scope': change['scope'], 'working': working, 'immutable': immutable})
            value = {'operation_id': row.id, 'updated_at': row.updated_at, 'observed': observed}
            return {**value, 'sha256': seal(value)}

    def recover(self, operation_id, *, preview_sha256, writers_stopped=False):
        self._writable()
        if writers_stopped is not True:
            raise ConfigurationConflict('configuration_writers_not_confirmed_stopped')
        request = {'kind': 'RECOVER', 'operation_id': operation_id, 'preview_sha256': preview_sha256,
                   'writers_stopped': True}
        key = f'recovery:{operation_id}:{preview_sha256}'
        with Session(self.managed.engine) as session:
            if self._replay(session, key, request):
                return self.operation(operation_id)
            files = self._files(session)
        with files.locked():
            if self.recovery_preview(operation_id)['sha256'] != preview_sha256:
                raise ConfigurationConflict('stale_configuration_recovery')
            with self.managed._write() as session:
                confirmation = self._operation(session, key, request, request, kind='RECOVER', status='APPLIED')
                confirmation.result = {'state': 'RECOVERY_CONFIRMED', 'operation_id': operation_id}
            return self._complete(operation_id, files)

    @staticmethod
    def _waiting(session, roots):
        """D238: current work that must finish (or be resolved explicitly) before a live switch."""
        from my_harness.storage.models import (
            ManagedCommitRow, PhaseRow, PhaseOperationRow, ProjectBootstrapRow, ProjectCreationOperationRow,
            ProjectImportRow,
        )
        reasons = []
        if session.scalar(select(ProjectCreationOperationRow.id).where(
                ProjectCreationOperationRow.reserved.is_(True)).limit(1)):
            reasons.append('project_creation')
        for root in sorted(roots):
            reasons += [f'job:{value}' for value in ProjectRegistryRepository._unfinished(session, root)]
            reasons += [f'phase_operation:{value}' for value in session.scalars(select(PhaseOperationRow.id)
                .join(PhaseRow, PhaseRow.id == PhaseOperationRow.phase_id).where(
                    PhaseRow.root == root, PhaseOperationRow.status.in_(('QUEUED', 'INTENT', 'INTERRUPTED'))))]
            reasons += [f'acceptance:{value}' for value in session.scalars(
                select(Run.id).where(Run.root == root, Run.status == 'ACCEPTANCE_READY'))]
            reasons += [f'commit:{value}' for value in session.scalars(
                select(ManagedCommitRow.operation_id).join(Run, Run.id == ManagedCommitRow.run_id)
                .where(Run.root == root, ManagedCommitRow.status == 'INTENT'))]
            for model, label in ((ProjectBootstrapRow, 'documents'), (ProjectImportRow, 'documents')):
                reasons += [f'{label}:{value}' for value in session.scalars(
                    select(model.id).where(model.root == root, model.status != 'COMPLETED'))]
        reasons += [f'assistance:{value}' for value in session.scalars(select(Operation.id).where(
            Operation.kind == 'ASSIST', Operation.status.in_(UNRESOLVED)))]
        return list(dict.fromkeys(reasons))

    def _roots(self, session, scopes):
        from my_harness.storage.models import (
            ChatConversationRow, CheckoutLockRow, PhaseRow, PlanningConversationRow, ProjectBootstrapRow,
            ProjectImportRow,
        )
        roots = set()
        if 'global' in scopes:
            roots.update(session.scalars(select(Project.root)))
            roots.update(session.scalars(select(Run.root)))
            roots.update(session.scalars(select(CheckoutLockRow.root)))
            roots.update(session.scalars(select(PhaseRow.root)))
            for model in (ChatConversationRow, PlanningConversationRow, ProjectBootstrapRow, ProjectImportRow):
                roots.update(session.scalars(select(model.root)))
        else:
            for scope in scopes:
                project = session.get(Project, scope[8:])
                if not project or project.status != 'ACTIVE':
                    raise ConfigurationConflict('project_identity_changed')
                roots.add(project.root)
        return roots

    def _live_blockers(self, session, scopes):
        """Live sets wait for current work; project-only sets still refuse documentary work (D226)."""
        roots = self._roots(session, scopes)
        if 'global' not in scopes and any(ProjectRegistryRepository._documentary_blockers(session, root)
                                          for root in roots):
            raise ConfigurationConflict('configuration_has_pending_work')
        return sorted(roots), self._waiting(session, roots)

    def waiting(self, references):
        """Current waiting reasons of a pending live set, recomputed on each read."""
        with Session(self.managed.engine) as session:
            return self._waiting(session, self._roots(session, {ref['scope'] for ref in references}))

    def _blockers(self, session, scopes):
        """D222 restart sets: any pending work refuses the activation."""
        from my_harness.storage.models import PhaseRow, PhaseOperationRow, ProjectCreationOperationRow
        if 'global' in scopes and session.scalar(select(ProjectCreationOperationRow.id).where(
                ProjectCreationOperationRow.reserved.is_(True)).limit(1)):
            raise ConfigurationConflict('pending_project_creation')
        roots = self._roots(session, scopes)
        for root in roots:
            if (ProjectRegistryRepository._unfinished(session, root)
                    or ProjectRegistryRepository._configuration_blockers(session, root)
                    or session.scalar(select(PhaseOperationRow.id).join(PhaseRow,
                        PhaseRow.id == PhaseOperationRow.phase_id).where(
                            PhaseRow.root == root,
                            PhaseOperationRow.status.in_(('QUEUED', 'INTENT', 'INTERRUPTED'))).limit(1))):
                raise ConfigurationConflict('configuration_has_pending_work')
        return sorted(roots)

    def _activation_preview(self, session, files, references, reason, *, promoting=False, stage=False):
        self._clear(session)
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ValueError(tr('configuration.reason'))
        if not isinstance(references, list) or not 1 <= len(references) <= 100:
            raise ValueError(tr('configuration.references'))
        refs, data_by_scope, seen = [], {}, set()
        for ref in sorted(references, key=lambda item: item['scope']):
            if set(ref) != {'scope', 'revision', 'sha256', 'expected_version'}:
                raise ValueError(tr('configuration.reference_exact'))
            scope = scope_name(ref['scope'])
            if (type(ref['revision']) is not int or ref['revision'] < 1
                    or type(ref['expected_version']) is not int or ref['expected_version'] < 0):
                raise ValueError(tr('configuration.reference_integer'))
            if scope in seen:
                raise ValueError(tr('configuration.activation_duplicate'))
            seen.add(scope)
            state = self._state(session, files, scope)
            candidate = self._ref(session, scope, ref['revision'])
            if (state['version'] != ref['expected_version'] or candidate is None
                    or candidate['sha256'] != ref['sha256']
                    or (not promoting and state['saved'] != candidate)):
                raise ConfigurationConflict('stale_configuration_activation')
            if state['status'] not in ('UNCONFIGURED', 'READY') and not (promoting and state['status'] == 'APPLY_PENDING'):
                raise ConfigurationConflict(state['status'].lower())
            if candidate['status'] != 'VALIDATED':
                raise ConfigurationConflict('configuration_draft_not_activatable')
            raw = files.read(files.immutable(scope, ref['revision'], ref['sha256']))
            if raw is None or digest(raw) != ref['sha256']:
                raise ConfigurationConflict('immutable_configuration_changed')
            # Revalidate environment-dependent constraints before each activation and promotion.
            data = self._candidate(session, {'scope': scope, 'text': raw.decode(), 'validated': True,
                'expected_version': ref['expected_version'], 'base_sha256': state['working_sha256'],
                'active_sha256': state['active']['sha256'] if state['active'] else None, 'import_external': False})
            data_by_scope[scope] = data
            refs.append({**ref, 'previous': state['active']})
        if 'global' in seen:
            from my_harness.services.configuration_import import imported
            legacy_import = imported(session)
            if legacy_import and not session.get(Scope, 'global').active_revision:
                required = {'project:' + item['id'] for item in legacy_import['projects']}
                if not required <= seen:
                    raise ConfigurationConflict('configuration_import_requires_all_projects')
                from my_harness.services.configuration_import import verify_registry
                verify_registry(session, legacy_import)
            affected = set(session.scalars(select(Scope.scope).where(Scope.scope != 'global',
                                                                    Scope.active_revision.is_not(None))))
            if not affected <= seen:
                raise ConfigurationConflict('global_impact_requires_project_revisions')
            global_ref = next(ref for ref in refs if ref['scope'] == 'global')
        else:
            global_head = session.get(Scope, 'global')
            if not global_head or not global_head.active_revision or global_head.pending_revision:
                raise ConfigurationConflict('active_global_configuration_required')
            state = self._state(session, files, 'global')
            if state['status'] != 'READY':
                raise ConfigurationConflict(state['status'].lower())
            global_ref = state['active']
        evidence = {}
        for scope, data in data_by_scope.items():
            if scope == 'global':
                continue
            if data['global'] != {'revision': global_ref['revision'], 'sha256': global_ref['sha256']}:
                raise ConfigurationConflict('project_global_reference_changed')
            if self.project_verifier is None:
                raise ConfigurationConflict('project_preparation_verifier_required')
            evidence[scope] = self.project_verifier(session, scope, data)
            if not isinstance(evidence[scope], dict) or not evidence[scope]:
                raise ConfigurationConflict('project_preparation_required')
        # D238: restart only for fields the running service cannot switch; the classifier is the runtime's.
        restart = []
        if 'global' in seen:
            restart = (self.restart_fields(session, data_by_scope['global']) if self.restart_fields
                       else ['service'])
        waiting = []
        if restart:
            roots = self._blockers(session, seen)
        else:
            roots, waiting = self._live_blockers(session, seen)
        value = {'format': FORMAT, 'kind': 'ACTIVATE', 'references': refs, 'reason': reason,
                 'impact': sorted(seen), 'roots': roots, 'evidence': evidence,
                 'restart_required': bool(restart)}
        if not restart:
            value.update(apply='live')
        if restart and self.restart_fields:
            value.update(apply='restart', restart_fields=restart)
        if stage and not restart and self.live_verifier:
            # Builds and checks the complete candidate runtime; never installs it or changes SQLite.
            self.live_verifier(refs)
        # Waiting reasons are current facts, not part of the confirmed policy: confirmation means
        # "apply at the next idle boundary", which may be immediately.
        return {**value, 'sha256': seal(value), 'waiting': waiting}

    def activation_preview(self, references, *, reason):
        self._writable()
        with Session(self.managed.engine) as session:
            return self._activation_preview(session, self._files(session), references, reason, stage=True)

    def activate(self, references, *, reason, preview_sha256, key):
        self._writable()
        request = {'kind': 'ACTIVATE', 'references': references, 'reason': reason, 'preview_sha256': preview_sha256}
        with self.managed._write() as session:
            replay = self._replay(session, key, request)
            if replay:
                return replay
            preview = self._activation_preview(session, self._files(session), references, reason)
            if preview['sha256'] != preview_sha256:
                raise ConfigurationConflict('stale_configuration_activation')
            registry = ProjectRegistryRepository(self.managed)
            waiting = preview.pop('waiting')
            # A global live set is always published by the runtime's promotion, which installs it.
            pending = preview['restart_required'] or bool(waiting) or 'global' in preview['impact']
            row = self._operation(session, key, request, preview, kind='ACTIVATE', status='APPLIED')
            for ref in preview['references']:
                head = session.get(Scope, ref['scope'])
                if pending:
                    head.pending_revision = ref['revision']
                    head.pending_operation_id = row.id
                else:
                    head.active_revision = ref['revision']
                head.version += 1
                head.updated_at = self.managed._now()
            for root in preview['roots']:
                registry._supersede_plans(session, root, max(ref['expected_version'] + 1 for ref in references))
            state = ('RESTART_REQUIRED' if preview['restart_required'] else 'APPLY_PENDING' if pending else 'ACTIVE')
            row.result = {'state': state, 'references': preview['references'],
                          **({'waiting': waiting} if waiting else {})}
            return operation_view(row)

    def promote_pending(self, *, activation_id, key, restarted=False, on_commit=None):
        """Recheck the complete pending set and atomically promote it.

        A restart set needs the explicit startup assertion; this method never infers a stopped writer
        from a lease. A live set (D238) is promoted by the running service only without waiting work;
        `on_commit` installs its staged runtime while the write barrier is still held.
        """
        self._writable()
        request = {'kind': 'PROMOTE', 'activation_id': activation_id}
        with self.managed._write() as session:
            replay = self._replay(session, key, request)
            if replay:
                return replay
            self._clear(session)
            files = self._files(session)
            activation = session.get(Operation, activation_id)
            if not activation or activation.kind != 'ACTIVATE' or not (
                    activation.payload['restart_required'] or live(activation)):
                raise ConfigurationConflict('unknown_pending_configuration_activation')
            if not live(activation) and restarted is not True:
                raise ConfigurationConflict('configuration_restart_required')
            references = activation.payload['references']
            # Reuse the exact activation validation against temporary in-transaction heads.
            # Rollback restores every pending reference if any check fails.
            candidate_refs = []
            for ref in references:
                head = session.get(Scope, ref['scope'])
                if (not head or head.pending_revision != ref['revision']
                        or head.pending_operation_id != activation_id):
                    raise ConfigurationConflict('pending_configuration_changed')
                head.pending_revision = None
                head.pending_operation_id = None
                candidate_refs.append({k: ref[k] for k in ('scope', 'revision', 'sha256')} |
                                      {'expected_version': head.version})
            session.flush()
            preview = self._activation_preview(session, files, candidate_refs, activation.payload['reason'], promoting=True)
            if preview['evidence'] != activation.payload['evidence']:
                raise ConfigurationConflict('configuration_preparation_changed')
            if live(activation) and (preview['restart_required'] or preview['waiting']):
                raise ConfigurationConflict('configuration_has_pending_work')
            from my_harness.services.configuration_import import promote_registry
            promote_registry(session, self, references, self.managed._now())
            for ref in references:
                head = session.get(Scope, ref['scope'])
                head.active_revision, head.version = ref['revision'], head.version + 1
                head.updated_at = self.managed._now()
            row = self._operation(session, key, request, {'activation_id': activation_id}, kind='PROMOTE', status='APPLIED')
            row.result = {'state': 'ACTIVE', 'references': references}
            if on_commit is not None:
                session.flush()
                on_commit()
            return operation_view(row)

    def fail_pending(self, *, activation_id, key, code, details=None):
        """D238: a live set that cannot be staged at the boundary is withdrawn; the active set stays."""
        self._writable()
        request = {'kind': 'PROMOTE', 'activation_id': activation_id}
        with self.managed._write() as session:
            replay = self._replay(session, key, request)
            if replay:
                return replay
            activation = session.get(Operation, activation_id)
            if not live(activation):
                raise ConfigurationConflict('unknown_pending_configuration_activation')
            for ref in activation.payload['references']:
                head = session.get(Scope, ref['scope'])
                if head.pending_operation_id != activation_id or head.pending_revision != ref['revision']:
                    raise ConfigurationConflict('pending_configuration_changed')
                head.pending_revision, head.pending_operation_id = None, None
                head.version += 1
                head.updated_at = self.managed._now()
            row = self._operation(session, key, request, {'activation_id': activation_id}, kind='PROMOTE', status='APPLIED')
            row.result = {'state': 'FAILED', 'activation_id': activation_id, 'code': code, 'details': details or []}
            return operation_view(row)

    def cancel_pending(self, *, activation_id, expected_versions, reason, key):
        """Explicit CAS cancellation; saved content and previous authority are retained."""
        self._writable()
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ValueError(tr('configuration.reason'))
        request = {'kind': 'CANCEL', 'activation_id': activation_id, 'expected_versions': expected_versions,
                   'reason': reason}
        with self.managed._write() as session:
            replay = self._replay(session, key, request)
            if replay:
                return replay
            self._clear(session)
            self._files(session)
            activation = session.get(Operation, activation_id)
            if not activation or activation.kind != 'ACTIVATE' or not (
                    activation.payload['restart_required'] or live(activation)):
                raise ConfigurationConflict('unknown_pending_configuration_activation')
            refs = activation.payload['references']
            if set(expected_versions) != {ref['scope'] for ref in refs}:
                raise ConfigurationConflict('pending_configuration_changed')
            for ref in refs:
                head = session.get(Scope, ref['scope'])
                if (head.pending_revision != ref['revision'] or head.version != expected_versions[ref['scope']]
                        or head.pending_operation_id != activation_id):
                    raise ConfigurationConflict('pending_configuration_changed')
                head.pending_revision, head.version = None, head.version + 1
                head.pending_operation_id = None
                head.updated_at = self.managed._now()
            row = self._operation(session, key, request, request, kind='CANCEL', status='APPLIED')
            row.result = {'state': 'CANCELLED', 'activation_id': activation_id}
            return operation_view(row)

    def discard_external(self, scope, *, expected_version, observed_sha256, reason, key):
        """Restore the last saved working copy only after explicit CAS of external bytes.

        Uses the same recoverable publication journal, preserving unknown bytes as
        the sealed base in the confirmed operation. Immutable authority is never repaired.
        """
        self._writable()
        request = {'kind': 'DISCARD', 'scope': scope, 'expected_version': expected_version,
                   'observed_sha256': observed_sha256, 'reason': reason}
        with Session(self.managed.engine) as session:
            replay = self._replay(session, key, request)
            if replay:
                return replay
        state = self.read(scope)
        if state['status'] != 'EXTERNAL_CHANGE' or not state['saved'] or state['version'] != expected_version:
            raise ConfigurationConflict('external_configuration_change_required')
        text = self.document(scope, state['saved']['revision'])
        change = {'scope': scope, 'text': text, 'validated': state['saved']['status'] == 'VALIDATED',
                  'expected_version': expected_version, 'base_sha256': observed_sha256,
                  'active_sha256': state['active']['sha256'] if state['active'] else None, 'import_external': True}
        preview = self.preview([change], reason=reason)
        return self._save([change], reason=reason, preview_sha256=preview['sha256'], key=key, request=request)
