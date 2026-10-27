"""D116 journal. The SQLite write lock serializes authority, reservations, short effects and registration."""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.storage.models import (
    ProjectCreationRootRow as Root, ProjectCreationRootEventRow as RootEvent,
    ProjectCreationOperationRow as Operation, ProjectCreationOperationEventRow as Event,
    RegisteredProjectRow as Project,
)
from my_harness.storage.permissions import actor
from my_harness.services.project_registry import digest, RegistryError, _inside
from my_harness.i18n import tr


def root_view(row):
    return {key: getattr(row, key) for key in ('version', 'status', 'path', 'identity', 'row_sha256', 'updated_at')} if row else {
        'version': 0, 'status': 'ABSENT', 'path': None, 'identity': None, 'row_sha256': None, 'updated_at': None}


def operation_view(row):
    return {key: getattr(row, key) for key in (
        'id', 'version', 'project_id', 'directory_name', 'target', 'reserved', 'authority', 'intent', 'intent_sha256',
        'status', 'child_identity', 'result', 'diagnostic', 'created_at', 'updated_at')}


class CreationRepository:
    def __init__(self, managed):
        self.managed = managed

    def root(self):
        with Session(self.managed.engine) as session:
            return root_view(session.get(Root, 1))

    def roots_history(self):
        with Session(self.managed.engine) as session:
            return [e.payload for e in session.scalars(select(RootEvent).order_by(RootEvent.version))]

    def read(self, operation_id):
        with Session(self.managed.engine) as session:
            row = self.require(session, operation_id)
            return {**operation_view(row), 'history': [e.payload for e in session.scalars(
                select(Event).where(Event.operation_id == row.id).order_by(Event.version))]}

    def operations(self):
        with Session(self.managed.engine) as session:
            return [operation_view(row) for row in session.scalars(select(Operation).order_by(Operation.created_at))]

    @staticmethod
    def require(session, operation_id):
        row = session.get(Operation, operation_id)
        if row is None:
            raise LookupError(tr('creation.unknown'))
        return row

    def event(self, session, row, kind, *, reason=None, key=None, request_sha256=None):
        previous = session.scalar(select(Event).where(Event.operation_id == row.id).order_by(Event.version.desc()))
        row.version += 1
        row.updated_at = self.managed._now()
        payload = {'version': row.version, 'kind': kind, 'operation': operation_view(row), 'actor': actor(),
                   'reason': reason, 'recorded_at': row.updated_at,
                   'previous_sha256': previous.payload['sha256'] if previous else None}
        payload['sha256'] = digest(payload)
        session.add(Event(operation_id=row.id, version=row.version, payload=payload,
                          idempotency_key=key, request_sha256=request_sha256))
        session.flush()

    @staticmethod
    def conflicts(session, project_id, target, *, operation_id=None):
        """Also used from the D078 registration: no uncertain reservation is adopted as an existing checkout."""
        for row in session.scalars(select(Operation).where(Operation.reserved.is_(True))):
            if row.id != operation_id and (row.project_id == project_id or _inside(Path(row.target), Path(target))):
                raise RegistryError(409, 'target_reserved', tr('creation.reserved'))
        for row in session.scalars(select(Project)):
            if row.id == project_id:
                raise RegistryError(409, 'duplicate_id', tr('creation.id_registered'))
            if row.status == 'ACTIVE' and _inside(Path(row.root), Path(target)):
                raise RegistryError(409, 'root_taken', tr('creation.target_taken'))
