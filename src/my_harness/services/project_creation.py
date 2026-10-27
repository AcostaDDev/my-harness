"""P009-T002 / D116: a UI authority for new direct children; no agents or Git.

`project-creation-2` (P011-T008, D167) seals the chosen work language in the intent; registering the child
associates it with the new root in the same transaction. `project-creation-1` intents still register, without one.
"""
from contextlib import contextmanager
from dataclasses import asdict
import os
from pathlib import Path
import stat
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.i18n import tr
from my_harness.services.managed_runtime import PROJECT_ID
from my_harness.services.project_registry import (
    RegistryError, RESERVED_IDS, digest, _inside, _within, trust_statement,
)
from my_harness.storage.models import (
    ProjectCreationRootRow as Root, ProjectCreationRootEventRow as RootEvent,
    ProjectCreationOperationRow as Operation, ProjectCreationOperationEventRow as Event,
    RegisteredProjectRow as Project, RegisteredProjectEventRow as ProjectEvent,
)
from my_harness.storage.permissions import actor
from my_harness.storage.project_creation import CreationRepository, root_view
from my_harness.storage.registry import RegistryConflict, confirm_work_language


def permission_statement():
    """Shown with the folder and its previews, in the visual language of each emission (P011-T021)."""
    return tr('creation.permission')


CONTRACT = 'project-creation-2'
CONTRACTS = ('project-creation-1', CONTRACT)


def identity(info):
    return {'device': info.st_dev, 'inode': info.st_ino}


def normalized(value):
    if not isinstance(value, str) or not value or '\0' in value or '..' in value.split('/'):
        raise RegistryError(422, 'root_invalid', tr('creation.path_required'))
    path = Path(os.path.normpath(value))
    if not path.is_absolute():
        raise RegistryError(422, 'root_not_absolute', tr('creation.absolute'))
    return Path('/' + str(path).lstrip('/'))


@contextmanager
def directory(path):
    """Each component by fd and O_NOFOLLOW. A link is never resolved silently."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def exists(fd, name):
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


class ProjectCreation:
    def __init__(self, runtime):
        self.runtime, self.registry = runtime, runtime.registry
        self.repository = CreationRepository(runtime.repository)
        self.lock = self.registry._lock

    def reconcile(self):
        """Startup: classifies uncertain effects; never creates, adopts or deletes folders."""
        if self.registry.registrar is None:
            return
        with self.lock, self.runtime.repository._write() as session:
            for row in session.scalars(select(Operation).where(Operation.status == 'INTENDED')):
                try:
                    with directory(Path(row.authority['path'])) as fd:
                        changed = identity(os.fstat(fd)) != row.authority['identity']
                        present = exists(fd, row.directory_name)
                    if not changed and not present:
                        continue
                    row.status = 'RECOVERY_REQUIRED' if present else 'BLOCKED'
                    row.diagnostic = tr('creation.restart_unproven')
                except OSError:
                    row.status, row.diagnostic = 'RECOVERY_REQUIRED', tr('creation.restart_unknown')
                self.repository.event(session, row, 'restart_observed')

    def require(self, *, bootstrap=False):
        registrar = self.registry._require()
        if bootstrap and not registrar.bootstrap_enabled:
            raise RegistryError(409, 'bootstrap_not_allowed', tr('creation.bootstrap'))
        return registrar

    def protected(self):
        registrar = self.require()
        db = self.runtime.database
        return (registrar.state, registrar.source, db, Path(str(db) + '-wal'), Path(str(db) + '-shm'),
                self.runtime.migrations_dir)

    def parent(self, value):
        path = normalized(value)
        try:
            with directory(path) as fd:
                info = identity(os.fstat(fd))
                if not os.access(path, os.W_OK | os.X_OK):
                    raise RegistryError(422, 'root_unwritable', tr('creation.unwritable'))
            # Static inspection: runs no Git and reads no repository configuration.
            if any(os.path.lexists(p / '.git') for p in (path, *path.parents)):
                raise RegistryError(422, 'root_in_repository', tr('creation.in_repository'))
            if any(_within(path, p) for p in self.protected() if p is not None):
                raise RegistryError(422, 'root_service_state', tr('creation.in_state'))
            roots = [p.context.root for p in self.runtime.projects.values()]
            roots += [Path(p['root']) for p in self.registry.repository.rows() if p['status'] == 'ACTIVE']
            if any(_within(path, p) for p in roots):
                raise RegistryError(422, 'root_taken', tr('creation.in_checkout'))
            return str(path), info
        except OSError:
            raise RegistryError(422, 'root_unavailable', tr('creation.unavailable')) from None

    def read_root(self):
        available = self.registry.registrar is not None
        root = self.repository.root()
        return {**root, 'available': available,
                'diagnostic': None if available else tr('creation.registrable'),
                'bootstrap_enabled': available and self.registry.registrar.bootstrap_enabled,
                'permission_statement': permission_statement(), 'history': self.repository.roots_history(),
                'operations': self.repository.operations()}

    def root_preview(self, body, *, session=None):
        self.require()
        current = root_view(session.get(Root, 1)) if session is not None else self.repository.root()
        if current['version'] != body['expected_version']:
            raise RegistryError(409, 'stale_version', tr('creation.root_stale'))
        if body['action'] == 'select':
            path, info = self.parent(body.get('path'))
        else:
            if body.get('path') is not None:
                raise RegistryError(422, 'root_invalid', tr('creation.retire_path'))
            if current['status'] != 'ACTIVE':
                raise RegistryError(409, 'root_revoked', tr('creation.retire_none'))
            path, info = None, None
        after = {'version': current['version'] + 1,
                 'status': 'ACTIVE' if body['action'] == 'select' else 'REVOKED', 'path': path, 'identity': info}
        return {'action': body['action'], 'expected_version': current['version'], 'root': after,
                'permission_statement': permission_statement(), 'preview_sha256': digest({'before': current, 'after': after})}

    @staticmethod
    def same_request(saved, request_sha256):
        if saved.request_sha256 != request_sha256:
            raise RegistryError(409, 'idempotency_conflict', tr('creation.key_reused'))

    def root_apply(self, body, key):
        request_sha256 = digest(body)
        with self.lock, self.runtime.repository._write() as session:
            previous = session.scalar(select(RootEvent).where(RootEvent.idempotency_key == key))
            if previous:
                self.same_request(previous, request_sha256)
                return {**previous.payload['preview'], 'replayed': True}
            preview = self.root_preview(body['change'], session=session)
            if preview['preview_sha256'] != body['preview_sha256']:
                raise RegistryError(409, 'preview_changed', tr('creation.root_changed'))
            after = preview['root']
            if after['status'] == 'ACTIVE' and body.get('confirm_path') != after['path']:
                raise RegistryError(409, 'root_unconfirmed', tr('creation.root_confirm'))
            row = session.get(Root, 1)
            before = root_view(row)
            if row is None:
                row = Root(id=1)
                session.add(row)
            for field, value in after.items():
                setattr(row, field, value)
            row.row_sha256, row.updated_at = digest(after), self.runtime.repository._now()
            event = {'action': body['change']['action'], 'before': before, 'after': root_view(row),
                     'preview': preview, 'actor': actor(), 'reason': body.get('reason'),
                     'previous_sha256': before['row_sha256'], 'recorded_at': row.updated_at}
            event['sha256'] = digest(event)
            session.add(RootEvent(version=row.version, idempotency_key=key,
                                  request_sha256=request_sha256, payload=event))
            for operation in session.scalars(select(Operation).where(
                    Operation.status.in_(('INTENDED', 'DIRECTORY_CREATED')))):
                operation.status, operation.diagnostic = 'BLOCKED', tr('creation.root_replaced')
                self.repository.event(session, operation, 'root_changed')
            return {**preview, 'replayed': False}

    def authority(self, expected, *, session=None):
        self.require(bootstrap=True)
        root = root_view(session.get(Root, 1)) if session is not None else self.repository.root()
        if root['status'] != 'ACTIVE' or root['version'] != expected:
            raise RegistryError(409, 'root_revoked', tr('creation.root_revoked'))
        path, info = self.parent(root['path'])
        if info != root['identity']:
            raise RegistryError(409, 'target_identity_changed', tr('creation.parent_changed'))
        return {k: root[k] for k in ('version', 'path', 'identity', 'row_sha256')}

    def conflicts(self, session, project_id, target, *, operation_id=None):
        self.repository.conflicts(session, project_id, target, operation_id=operation_id)
        self.registry._conflicts(project_id, Path(target), creation_id=operation_id)
        if any(_inside(Path(target), p) for p in self.protected() if p is not None):
            raise RegistryError(422, 'root_service_state', tr('creation.target_state'))

    def preview(self, body, *, session=None):
        if session is None:
            with Session(self.runtime.engine) as read:
                return self.preview(body, session=read)
        project_id, name = body['project_id'], body['directory_name']
        if not PROJECT_ID.fullmatch(project_id) or project_id in RESERVED_IDS:
            raise RegistryError(422, 'invalid_id', tr('creation.invalid_id'))
        if not PROJECT_ID.fullmatch(name) or name in ('.', '..'):
            raise RegistryError(422, 'invalid_directory_name', tr('creation.directory_name', pattern=PROJECT_ID.pattern))
        authority = self.authority(body['root_version'], session=session)
        target = str(Path(authority['path']) / name)
        self.conflicts(session, project_id, target)
        with directory(Path(authority['path'])) as fd:
            if identity(os.fstat(fd)) != authority['identity']:
                raise RegistryError(409, 'target_identity_changed', tr('creation.parent_changed'))
            if exists(fd, name):
                raise RegistryError(409, 'target_exists', tr('creation.target_exists'))
        language = self.registry.work_language_preview(body.get('work_language'), target, 'creation')
        row = {k: v for k, v in body.items()
               if k not in ('directory_name', 'root_version', 'project_id', 'work_language') and v is not None}
        row.update(id=project_id, root=target, repository_trusted=True, bootstrap_enabled=True)
        composed = self.registry._compose(row, (1, digest(row)), new_directory=True)
        intent = {'contract': CONTRACT, 'authority': authority, 'row': row, 'target': target,
                  'directory_name': name, **composed, 'trust_statement': trust_statement(), 'permission_statement': permission_statement(),
                  'work_language_seal': self.registry.work_language_seal(language)}
        # The provenance shown (default and its version) stays outside the hash: see `work_language_seal`.
        return {**intent, 'work_language': language, 'preview_sha256': digest(intent)}

    def confirm(self, body, key):
        with self.lock:
            with self.runtime.repository._write() as session:
                previous = session.scalar(select(Operation).where(Operation.idempotency_key == key))
                if previous:
                    self.same_request(previous, digest(body))
                    return self.repository.read(previous.id)
                preview = self.preview(body['change'], session=session)
                if body['preview_sha256'] != preview['preview_sha256']:
                    raise RegistryError(409, 'preview_changed', tr('creation.preview_changed'))
                if body['trust_root'] != preview['target']:
                    raise RegistryError(409, 'trust_unconfirmed', tr('creation.trust_unconfirmed'))
                now = self.runtime.repository._now()
                row = Operation(id=str(uuid4()), idempotency_key=key, request_sha256=digest(body), version=0,
                                project_id=body['change']['project_id'], directory_name=preview['directory_name'],
                                target=preview['target'], reserved=True, authority=preview['authority'], intent=preview,
                                intent_sha256=digest(preview), status='INTENDED', created_at=now, updated_at=now)
                session.add(row)
                self.repository.event(session, row, 'intended', reason=body.get('reason'))
                operation_id = row.id
            self.advance(operation_id)
            return self.repository.read(operation_id)

    def check_intent(self, session, row):
        authority = self.authority(row.authority['version'], session=session)
        if authority != row.authority or digest(row.intent) != row.intent_sha256 or row.intent['contract'] not in CONTRACTS:
            raise RegistryError(409, 'recovery_required', tr('creation.intent_incompatible'))
        self.conflicts(session, row.project_id, row.target, operation_id=row.id)
        composed = self.registry._compose(row.intent['row'], (1, digest(row.intent['row'])),
                                          new_directory=row.status == 'INTENDED')
        versions = composed['versions'] if row.status == 'INTENDED' else dict(composed[0].versions)
        profile_sha256 = (composed['profile_details']['sha256'] if row.status == 'INTENDED'
                          else digest(asdict(composed[0].context.profile)) if hasattr(composed[0].context, 'profile') else None)
        if versions != row.intent['versions'] or profile_sha256 != row.intent['profile_details']['sha256']:
            raise RegistryError(409, 'preview_changed', tr('creation.composition_changed'))

    @contextmanager
    def owned_child(self, row):
        with directory(Path(row.authority['path'])) as parent_fd:
            if identity(os.fstat(parent_fd)) != row.authority['identity']:
                raise RegistryError(409, 'target_identity_changed', tr('creation.parent_changed'))
            fd = os.open(row.directory_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            try:
                if identity(os.fstat(fd)) != row.child_identity:
                    raise RegistryError(409, 'target_identity_changed', tr('creation.child_changed'))
                if os.listdir(fd):
                    raise RegistryError(409, 'target_changed', tr('creation.child_foreign'))
                yield fd
                if identity(os.stat(row.directory_name, dir_fd=parent_fd, follow_symlinks=False)) != row.child_identity:
                    raise RegistryError(409, 'target_identity_changed', tr('creation.child_changed'))
                path, info = self.parent(row.authority['path'])
                if info != row.authority['identity']:
                    raise RegistryError(409, 'target_identity_changed', tr('creation.parent_changed'))
            finally:
                os.close(fd)

    def advance(self, operation_id):
        try:
            # Intent already confirmed before mkdir. SQLite excludes retirement/change during each short effect.
            with self.runtime.repository._write() as session:
                row = self.repository.require(session, operation_id)
                if row.status == 'INTENDED':
                    self.check_intent(session, row)
                    with directory(Path(row.authority['path'])) as fd:
                        if identity(os.fstat(fd)) != row.authority['identity']:
                            raise RegistryError(409, 'target_identity_changed', tr('creation.parent_changed'))
                        if exists(fd, row.directory_name):
                            raise RegistryError(409, 'recovery_required', tr('creation.target_unproven'))
                        os.mkdir(row.directory_name, mode=0o755, dir_fd=fd)
                        child = os.open(row.directory_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        try:
                            row.child_identity = identity(os.fstat(child))
                        finally:
                            os.close(child)
                        os.fsync(fd)
                        if self.parent(row.authority['path'])[1] != row.authority['identity']:
                            raise RegistryError(409, 'target_identity_changed', tr('creation.parent_changed'))
                    row.status = 'DIRECTORY_CREATED'
                    self.repository.event(session, row, 'directory_created')
            with self.runtime.repository._write() as session:
                row = self.repository.require(session, operation_id)
                if row.status != 'DIRECTORY_CREATED':
                    return
                self.check_intent(session, row)
                with self.owned_child(row):
                    intent = row.intent
                    now = self.runtime.repository._now()
                    project = Project(id=row.project_id, version=1, status='ACTIVE', root=row.target,
                                      composition=intent['row'].get('composition'), profile=intent['profile'], row=intent['row'],
                                      row_sha256=digest(intent['row']), creation_id=row.id,
                                      trust={'confirmed': True, 'root': row.target, 'statement': intent['trust_statement'], 'actor': actor()},
                                      created_at=now, updated_at=now)
                    session.add(project)
                    session.flush()
                    session.add(ProjectEvent(project_id=project.id, version=1, action='register', row=project.row,
                                             row_sha256=project.row_sha256, previous_sha256=None,
                                             preview_sha256=intent['preview_sha256'], actor=actor(),
                                             reason=tr('creation.confirmed', id=row.id), recorded_at=now))
                    if 'work_language_seal' in intent:
                        try:
                            confirm_work_language(session, project.id, row.target, intent['work_language_seal'],
                                                  'creation', intent['preview_sha256'], 'Creation ' + row.id, now)
                        except RegistryConflict as exc:
                            raise RegistryError(409, exc.code, str(exc)) from None
                    row.status, row.reserved = 'REGISTERED', False
                    row.result = {'project_id': project.id, 'root': project.root, 'creation_id': row.id}
                    self.repository.event(session, row, 'registered')
            self.registry.load()
        except (RegistryError, OSError) as error:
            with self.runtime.repository._write() as session:
                row = self.repository.require(session, operation_id)
                if row.status == 'REGISTERED':
                    raise
                row.status = 'RECOVERY_REQUIRED' if isinstance(error, OSError) or error.code == 'recovery_required' else 'BLOCKED'
                row.diagnostic = str(error) if isinstance(error, RegistryError) else tr('creation.uncertain')
                self.repository.event(session, row, 'stopped')

    def resume_preview(self, operation_id, body, *, session=None):
        if session is None:
            with Session(self.runtime.engine) as read:
                return self.resume_preview(operation_id, body, session=read)
        row = self.repository.require(session, operation_id)
        if row.version != body['expected_version']:
            raise RegistryError(409, 'stale_version', tr('creation.stale'))
        if row.status in ('REGISTERED', 'CANCELLED', 'RECOVERY_REQUIRED'):
            raise RegistryError(409, 'recovery_required', tr('creation.not_resumable'))
        authority = self.authority(body['root_version'], session=session)
        if (authority['path'], authority['identity']) != (row.authority['path'], row.authority['identity']):
            raise RegistryError(409, 'target_identity_changed', tr('creation.same_parent'))
        if row.child_identity is None:
            if authority != row.authority or os.path.lexists(row.target):
                raise RegistryError(409, 'recovery_required', tr('creation.expired'))
        else:
            with self.owned_child(row):
                pass
        self.conflicts(session, row.project_id, row.target, operation_id=row.id)
        composed = self.registry._compose(row.intent['row'], (1, digest(row.intent['row'])),
                                          new_directory=row.child_identity is None)
        versions = composed['versions'] if row.child_identity is None else dict(composed[0].versions)
        profile_sha256 = (composed['profile_details']['sha256'] if row.child_identity is None
                          else digest(asdict(composed[0].context.profile)) if hasattr(composed[0].context, 'profile') else None)
        if versions != row.intent['versions'] or profile_sha256 != row.intent['profile_details']['sha256']:
            raise RegistryError(409, 'preview_changed', tr('creation.original_changed'))
        preview = {'operation_id': row.id, 'expected_version': row.version, 'authority': authority,
                   'intent_sha256': row.intent_sha256, 'target': row.target}
        return {**preview, 'preview_sha256': digest(preview)}

    def resume(self, operation_id, body, key):
        with self.lock:
            with self.runtime.repository._write() as session:
                replay = session.scalar(select(Event).where(Event.idempotency_key == key))
                request_sha256 = digest({'operation_id': operation_id, **body})
                if replay:
                    self.same_request(replay, request_sha256)
                    return self.repository.read(operation_id)
                preview = self.resume_preview(operation_id, body['change'], session=session)
                if preview['preview_sha256'] != body['preview_sha256']:
                    raise RegistryError(409, 'preview_changed', tr('creation.resume_changed'))
                row = self.repository.require(session, operation_id)
                row.authority = preview['authority']
                row.status, row.diagnostic = ('DIRECTORY_CREATED' if row.child_identity else 'INTENDED'), None
                self.repository.event(session, row, 'resume_confirmed', reason=body.get('reason'), key=key,
                                      request_sha256=request_sha256)
            self.advance(operation_id)
            return self.repository.read(operation_id)

    def cancel(self, operation_id, body, key):
        with self.lock, self.runtime.repository._write() as session:
            replay = session.scalar(select(Event).where(Event.idempotency_key == key))
            request_sha256 = digest({'operation_id': operation_id, **body})
            if replay:
                self.same_request(replay, request_sha256)
                return self.repository.read(operation_id)
            row = self.repository.require(session, operation_id)
            if row.version != body['expected_version'] or body['intent_sha256'] != row.intent_sha256:
                raise RegistryError(409, 'stale_version', tr('creation.stale'))
            if row.status == 'REGISTERED' or (row.status == 'CANCELLED' and not row.reserved):
                raise RegistryError(409, 'recovery_required', tr('creation.finished'))
            # Release only if absence under the same parent is established. Never delete or adopt.
            try:
                with directory(Path(row.authority['path'])) as fd:
                    if identity(os.fstat(fd)) == row.authority['identity'] and not exists(fd, row.directory_name):
                        row.reserved = False
            except OSError:
                pass
            row.status = 'CANCELLED'
            row.diagnostic = tr('creation.cancelled_kept') if row.reserved else tr('creation.cancelled')
            self.repository.event(session, row, 'cancelled', reason=body.get('reason'), key=key,
                                  request_sha256=request_sha256)
            operation_id = row.id
        return self.repository.read(operation_id)
