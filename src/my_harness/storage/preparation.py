"""Preparation ownership/journal. No run, attempt or managed-event surrogate."""
from datetime import datetime, timedelta
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from my_harness.adapters.processes import liveness
from my_harness.storage import accounting
from my_harness.storage.managed import Conflict, OwnershipLost
from my_harness.storage.models import (
    CheckoutLockRow as Lock, ManagedProcessRow as Process,
    ProjectPreparationOperationRow as Operation, ProjectPreparationStepRow as Step,
    ProjectPreparationEventRow as Event,
)
from my_harness.storage.permissions import actor
from my_harness.i18n import tr


def _process(row):
    return {'spec': row.spec, 'status': row.status, 'identity': row.identity, 'capture': row.capture}


class PreparationRepository:
    def __init__(self, managed):
        self.managed = managed

    @staticmethod
    def require(session, operation_id):
        row = session.get(Operation, operation_id)
        if row is None:
            raise LookupError(tr('preparation.unknown_preparation'))
        return row

    def event(self, session, row, kind, payload=None):
        row.version += 1
        row.updated_at = self.managed._now()
        session.add(Event(operation_id=row.id, version=row.version, kind=kind,
                          payload={'actor': actor(), **(payload or {})}, recorded_at=row.updated_at))

    def read(self, operation_id, *, summary=False):
        with Session(self.managed.engine) as session:
            row = self.require(session, operation_id)
            fields = ('id', 'project_id', 'version', 'status', 'plan', 'plan_sha256', 'previous_id',
                      'receipt', 'diagnostic', 'cancel_requested', 'owner_closed', 'created_at', 'updated_at')
            values = {key: getattr(row, key) for key in fields}
            if summary and values['receipt']:
                values['receipt'] = {key: values['receipt'][key] for key in ('commit', 'operation_id', 'recipe')}
            return {**values,
                'steps': [{'id': s.id, 'number': s.number, 'spec': s.spec, 'status': s.status, 'evidence': None if summary else s.evidence}
                          for s in session.scalars(select(Step).options(*([defer(Step.evidence)] if summary else []))
                                                  .where(Step.operation_id == row.id).order_by(Step.number))],
                'events': [] if summary else [{'version': e.version, 'kind': e.kind, 'payload': e.payload, 'recorded_at': e.recorded_at}
                           for e in session.scalars(select(Event).where(Event.operation_id == row.id).order_by(Event.version))]}

    def owned(self, session, operation_id, token):
        row = self.require(session, operation_id)
        lock = session.get(Lock, row.root)
        if (row.status != 'ACTIVE' or row.owner_token != token or row.lease_until <= self.managed._now()
                or lock is None or lock.preparation_id != operation_id):
            raise OwnershipLost(tr('preparation.preparation_ownership_lease_lost'))
        return row

    def recover_expired(self):
        with self.managed._write() as session:
            for row in session.scalars(select(Operation).where(
                    Operation.status == 'ACTIVE', Operation.lease_until <= self.managed._now())):
                row.status, row.diagnostic = 'RECOVERY_REQUIRED', tr('preparation.lease')
                self.event(session, row, 'lease_expired')

    def claim(self, lease_seconds):
        with self.managed._write() as session:
            # Expired work is classified, never replayed.
            for row in session.scalars(select(Operation).where(
                    Operation.status == 'ACTIVE', Operation.lease_until <= self.managed._now())):
                row.status, row.diagnostic = 'RECOVERY_REQUIRED', tr('preparation.lease')
                self.event(session, row, 'lease_expired')
            row = session.scalar(select(Operation).where(Operation.status == 'QUEUED').order_by(Operation.created_at))
            if row is None:
                return None
            lock = session.get(Lock, row.root)
            if lock is None or lock.preparation_id != row.id:
                raise Conflict('Preparation lacks its exclusive checkout lock')
            from my_harness.adapters.processes import identity
            row.status, row.owner_token, row.process_owner = 'ACTIVE', str(uuid4()), identity()
            row.owner_closed = False
            row.lease_until = (datetime.fromisoformat(self.managed._now()) + timedelta(seconds=lease_seconds)).isoformat(timespec='microseconds')
            self.event(session, row, 'owner_started', {'identity': row.process_owner})
            return row.id, row.owner_token

    def heartbeat(self, operation_id, token, lease_seconds):
        with self.managed._write() as session:
            row = self.owned(session, operation_id, token)
            row.lease_until = (datetime.fromisoformat(self.managed._now()) + timedelta(seconds=lease_seconds)).isoformat(timespec='microseconds')

    def cancelled(self, operation_id, token):
        with Session(self.managed.engine) as session:
            return self.owned(session, operation_id, token).cancel_requested

    def interrupted(self, session, row):
        """D251: the closing owner settles its own unfinished processes before `owner_closed`.

        The state comes from an independent group-liveness check, never from lease expiry or the stale row;
        a partial capture the adapter left beside its artifacts is kept as reported. A stored capture is never
        replaced, and nothing here completes a step or turns partial counters into totals."""
        for process in session.scalars(select(Process).where(Process.preparation_id == row.id,
                                                             Process.status == 'RUNNING')):
            if process.capture is not None or process.identity is None:
                continue
            state = liveness(process.identity, group=True)
            partial = None
            artifacts = (process.spec or {}).get('artifacts')
            if isinstance(artifacts, str):
                try:
                    partial = json.loads((Path(artifacts) / 'capture.json').read_text())
                except (OSError, ValueError):
                    partial = None
            capture = partial if isinstance(partial, dict) else {'status': 'interrupted'}
            process.capture = {**capture, 'reported_group_state': capture.get('group_state'), 'group_state': state,
                               'settled_by': 'closing_owner'}
            process.status = 'STOPPED' if state == 'dead' else 'UNCERTAIN'
            accounting.settle_process(session, 'preparation_step', process.id, _process(process),
                                      outcome='interrupted', now=self.managed._now())
            self.event(session, row, 'process_interrupted', {'process_id': process.id, 'status': process.status,
                                                             'group_state': state, 'partial_capture': partial is not None})

    @staticmethod
    def stopped(session, row):
        if row.process_owner and not row.owner_closed and liveness(row.process_owner) != 'dead':
            raise Conflict(tr('preparation.previous_preparation_owner_alive'))
        for process in session.scalars(select(Process).where(Process.preparation_id == row.id)):
            if process.identity is not None:
                if liveness(process.identity, group=True) != 'dead':
                    raise Conflict(tr('preparation.previous_preparation_process_group'))
            elif not row.owner_closed and row.process_owner and liveness(row.process_owner) != 'dead':
                raise Conflict(tr('managed.pending_spawn_requires_stopped'))

    def process_event(self, operation_id, token, command_id, kind, payload):
        with self.managed._write() as session:
            row = self.owned(session, operation_id, token)
            step = session.get(Step, command_id)
            if step is None or step.operation_id != row.id or step.status != 'STARTED':
                raise Conflict('Preparation process requires its started step')
            process = session.get(Process, command_id)
            if kind == 'intent':
                if process is not None or payload['spec']['adapter_version'] != 'preparation-commands-1':
                    raise Conflict('Exact preparation process intent required once')
                session.add(Process(id=command_id, preparation_id=row.id, spec=payload['spec'], status='PENDING'))
            else:
                if process is None or process.preparation_id != row.id:
                    raise Conflict('Unknown preparation process')
                if kind == 'spawned':
                    if process.status != 'PENDING' or process.identity is not None:
                        raise Conflict('Process identity cannot change')
                    process.identity, process.status = payload['identity'], 'RUNNING'
                elif kind == 'finished':
                    process.capture = payload['capture']
                    process.status = 'STOPPED' if process.capture['group_state'] == 'dead' else 'UNCERTAIN'
                elif kind != 'bytes':
                    raise Conflict('Unknown preparation process event')
            self.event(session, row, 'command_process_' + kind, {'command_id': command_id, **payload})


class PreparationJournal:
    def __init__(self, repository, operation_id, token):
        self.repository, self.operation_id, self.token = repository, operation_id, token

    def command_process_event(self, command_id, kind, payload):
        self.repository.process_event(self.operation_id, self.token, command_id, kind, payload)

    def cancel_requested(self):
        return self.repository.cancelled(self.operation_id, self.token)


class PreparationAgentJournal(PreparationJournal):
    """CLI evidence belongs to the preparation step, without synthetic runs/attempts."""

    def process_intent(self, step_id, spec):
        from my_harness.adapters.cli_agents import VERSION
        with self.repository.managed._write() as session:
            row = self.repository.owned(session, self.operation_id, self.token)
            step = session.get(Step, step_id)
            if (step is None or step.operation_id != row.id or step.status != 'STARTED'
                    or step.spec['kind'] != 'executor' or session.get(Process, step_id)
                    or spec.get('adapter_version') != VERSION
                    or row.plan['contract'] != 'project-profile-preparation-1'):
                raise Conflict('Exact preparation executor intent required once')
            session.add(Process(id=step_id, preparation_id=row.id, spec=spec, status='PENDING'))
            session.flush()
            # P001-T003: the executor intent is the expected invocation; no synthetic run or attempt.
            accounting.intend_preparation(session, row, step_id, spec, self.repository.managed._now())
            self.repository.event(session, row, 'executor_intended', {'step_id': step_id, 'spec': spec})

    def process_update(self, step_id, kind, payload):
        self.process_updates(step_id, ((kind, payload),))

    def process_updates(self, step_id, items):
        """D251: one guarded transaction per read chunk instead of one per parsed stream record."""
        with self.repository.managed._write() as session:
            row = self.repository.owned(session, self.operation_id, self.token)
            process = session.get(Process, step_id)
            if process is None or process.preparation_id != row.id:
                raise Conflict('Unknown preparation executor process')
            for kind, payload in items:
                if kind == 'process_spawned':
                    if process.status != 'PENDING' or process.identity is not None:
                        raise Conflict('Process identity cannot change')
                    process.identity, process.status = payload, 'RUNNING'
                elif kind == 'process_finished':
                    process.capture = payload
                    process.status = 'STOPPED' if payload.get('group_state') == 'dead' else 'UNCERTAIN'
                    accounting.settle_process(session, 'preparation_step', step_id, _process(process),
                                              outcome=payload.get('status'), now=self.repository.managed._now())
                self.repository.event(session, row, 'executor_' + kind, {'step_id': step_id, **payload})


def admit(session, root, versions, purpose):
    """Same SQLite write admission as registry changes and preparation confirmation."""
    if session.scalar(select(Operation.id).where(Operation.root == root, Operation.reserved.is_(True))):
        raise Conflict(tr('preparation.required_unresolved'))
    if (versions.get('project_recipe') or versions.get('project_configuration')) and purpose in ('task', 'phase_check', 'phase_close'):
        from pathlib import Path
        from my_harness.adapters.preparation import verify_receipt
        from my_harness.services.project_registry import digest
        receipt = session.scalar(select(Operation.receipt).where(Operation.root == root, Operation.status == 'COMPLETED'))
        if versions.get('project_configuration'):
            # The exact evidence selected for the frozen revision: its own receipt, or the one a confirmed
            # activation retained for a nontechnical or derived revision (D227, D238).
            from my_harness.services.configuration_editing import selected_receipt
            row = selected_receipt(session, 'project:' + str(versions.get('project_registry_id')), {
                'revision': int(versions.get('project_configuration_revision') or 0),
                'sha256': versions.get('project_configuration_sha256')})
            receipt = row.receipt if row is not None and row.root == root and row.status == 'COMPLETED' else None
            if not receipt or versions.get('project_environment_sha256') != digest(receipt):
                raise Conflict(tr('preparation.required_tasks'))
        elif (not receipt or versions.get('project_environment_sha256') != digest(receipt)
                or versions.get('recipe_config_sha256') != receipt['recipe_config_sha256']):
            raise Conflict(tr('preparation.required_tasks'))
        verify_receipt(Path(root), receipt)
