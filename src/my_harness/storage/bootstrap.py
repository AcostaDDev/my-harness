"""H4.2: bootstrap as an existing run/job; the phase is adopted together with the end of the job.

H6.5: with the v2 layout the preview comes from the definition conversation and the drafts of the
target (`storage/planning.py`); the intent, the adapter and the recovery are the same.

D088: the v1 creation (form, `project-foundation` template and one-turn discovery) is retired;
a context without a layout is rejected before any read or effect. The v1 operations already recorded
are still read."""
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine.contracts import context_snapshot, freeze
from my_harness.core.engine.documents import layout
from my_harness.core.engine.phases import digest
from my_harness.storage.managed import Conflict, _job
from my_harness.storage.models import (
    ProjectBootstrapRow as Bootstrap, ManagedRunRow as Run, ManagedJobRow as Job,
    PhaseRow as Phase, ManagedActivationRow as Activation,
)
from my_harness.storage.permissions import actor
from my_harness.i18n import tr

# D088 (P011-T022: catalog key, rendered when raised).
V1_RETIRED = 'bootstrap.v1_retired'


def unresolved(session, root):
    return session.scalar(select(Bootstrap.id).where(Bootstrap.root == root, Bootstrap.status != 'COMPLETED')) is not None


def _operation(session, run):
    op = session.scalar(select(Bootstrap).where(Bootstrap.run_id == run.id))
    if op is None:
        raise Conflict('Bootstrap run lacks its operation')
    return op


def settle(managed, session, run, outcome):
    from my_harness.storage.phases import insert_phase
    op = _operation(session, run)
    if op.status != 'QUEUED' or outcome != {'commit': op.intent['commit'], 'tree': op.intent['tree'],
            'documents': {d['path']: d['sha256'] for d in op.preview['documents']}}:
        raise Conflict('Bootstrap result must match its sealed intent')
    # The adopted base is the phase documents (v1: the six; v2: ROADMAP, DECISIONS, STATE, NEXT_STEPS).
    baseline = {path: outcome['documents'][path] for path in op.preview['phase']['documents']}
    pid = insert_phase(managed, session, op.root, op.preview['phase'], baseline,
                       source={'bootstrap_id': op.id, 'run_id': run.id, 'commit': outcome['commit']})
    op.phase_id, op.status, op.result, op.finished_at = pid, 'COMPLETED', outcome, managed._now()
    managed._event(session, run, 'bootstrap_completed', {'operation_id': op.id, 'phase_id': pid, **outcome})


def abort(managed, session, run, status, reason):
    op = _operation(session, run)
    op.status, op.finished_at = 'INTERRUPTED', managed._now()
    op.result = {'reason': reason, 'effect': 'uncertain', 'job_status': status}
    managed._event(session, run, 'bootstrap_interrupted', {'operation_id': op.id, 'reason': reason})


class BootstrapRepository:
    def __init__(self, managed):
        self.managed = managed

    def get(self, root):
        with Session(self.managed.engine) as session:
            op = session.scalar(select(Bootstrap).where(Bootstrap.root == str(root)))
            if op is None:
                return None
            run = session.get(Run, op.run_id)
            task = session.scalar(select(Run).where(Run.root == op.root, Run.purpose == 'task',
                Run.phase_id == op.preview['phase']['code'], Run.task_id == op.preview['first_task']['task_id'])
                .order_by(Run.created_at.desc(), Run.id.desc()).limit(1))
            return {**{key: getattr(op, key) for key in ('id', 'root', 'run_id', 'phase_id', 'status', 'preview',
                'intent', 'decision', 'result', 'created_at', 'finished_at')},
                'expected_version': run.version, 'run_status': run.status,
                'first_task_run': None if task is None else {'run_id': task.id, 'status': task.status}}

    def request(self, run_id):
        with Session(self.managed.engine) as session:
            op = _operation(session, session.get(Run, run_id))
            return {'preview': op.preview, 'intent': op.intent}

    @staticmethod
    def _empty_authority(session, root):
        if session.scalar(select(Job.id).join(Run, Run.id == Job.run_id).where(
                Run.root == root, Run.purpose == 'definition', Job.status.in_(('QUEUED', 'ACTIVE', 'RECOVERY_REQUIRED')))):
            raise Conflict(tr('planning.definition_turn_pending_accept'))
        if (session.scalar(select(Run.id).where(Run.root == root,
                                                Run.purpose.notin_(('bootstrap_discovery', 'definition'))))
                or session.scalar(select(Job.id).join(Run, Run.id == Job.run_id).where(Run.root == root,
                                      Job.status.in_(('QUEUED', 'ACTIVE', 'RECOVERY_REQUIRED'))))
                or session.scalar(select(Phase.id).where(Phase.root == root))
                or session.scalar(select(Activation.id).where(Activation.root == root,
                                      Activation.status.in_(('PREPARING', 'ACTIVE', 'REVERTING'))))):
            raise Conflict(tr('bootstrap.target_has_managed_history'))

    def preview(self, context, data, versions, writer):
        if layout(context) is None:
            raise ValueError(tr(V1_RETIRED))
        saved = self.get(context.root)
        if saved is not None:
            if saved['status'] == 'INTERRUPTED':
                return {**saved['preview'], 'resume_operation_id': saved['id'],
                        'expected_version': saved['expected_version']}
            raise Conflict(tr('bootstrap.bootstrap_already_exists_inspect'))
        with Session(self.managed.engine) as session:
            self._empty_authority(session, str(context.root))
        from my_harness.storage.planning import definition_acceptance
        if not isinstance(data, dict) or set(data) != {'conversation_id'}:
            raise ValueError(tr('planning.projects_documents_v2_created'))
        from my_harness.storage.profile_intake import documentary_profile
        rendered, binding = documentary_profile(self.managed, context, data['conversation_id'], writer, versions)
        content = {**definition_acceptance(self.managed, rendered, data, writer), **binding}
        shown = {**content, 'versions': versions,
                 'author': {'name': writer.identity.name, 'email': writer.identity.email},
                 'git': {'branch': 'main', 'message': 'Initialize project from confirmed bootstrap',
                         'timestamp': 'fixed at confirmation'}}
        shown['preview_sha256'] = digest(shown)
        return {**shown, 'resume_operation_id': None, 'expected_version': None}

    def submit(self, context, data, versions, writer, *, key, preview_sha256, confirmed, reason,
               resume_operation_id=None, expected_version=None):
        if confirmed is not True or not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('bootstrap.explicit_confirmation_brief_decisions'))
        marker = freeze({'action': 'bootstrap', 'root': str(context.root), 'input': data,
                         'preview_sha256': preview_sha256, 'confirmed': confirmed, 'reason': reason,
                         'resume_operation_id': resume_operation_id, 'expected_version': expected_version})
        with Session(self.managed.engine) as session:
            existing = self.managed._existing(session, key, marker)
            if existing:
                return _job(existing)
        try:
            shown = self.preview(context, data, versions, writer)
        except Conflict:
            with Session(self.managed.engine) as session:
                existing = self.managed._existing(session, key, marker)
                if existing:
                    return _job(existing)
            raise
        if (not shown['ready'] or shown['preview_sha256'] != preview_sha256
                or shown['resume_operation_id'] != resume_operation_id
                or shown['expected_version'] != expected_version
                or data != shown['input']):
            raise Conflict(tr('bootstrap.preview_changed_import_required'))
        operation_id = resume_operation_id or str(uuid4())
        intent = None if resume_operation_id else writer.seal_bootstrap(
            shown, operation_id, int(self.managed.clock().timestamp()))
        assessment = self.managed.guard.assess(context.root)
        with self.managed._write() as session:
            existing = self.managed._existing(session, key, marker)
            if existing:
                return _job(existing)
            if resume_operation_id:
                op = session.get(Bootstrap, resume_operation_id)
                if op is None or op.root != str(context.root) or op.status != 'INTERRUPTED':
                    raise Conflict(tr('bootstrap.exact_interrupted_bootstrap_resume'))
                run = session.get(Run, op.run_id)
                if (run.version != expected_version or run.context_json != context_snapshot(context)
                        or run.versions_json != freeze(versions) or op.preview['author'] != {
                            'name': writer.identity.name, 'email': writer.identity.email}):
                    raise Conflict(tr('bootstrap.frozen_bootstrap_version_context'))
                if session.scalar(select(Job.id).where(Job.run_id == run.id,
                                    Job.status.in_(('QUEUED', 'ACTIVE', 'RECOVERY_REQUIRED')))):
                    raise Conflict(tr('bootstrap.confirm_stopped_bootstrap_writer'))
                job = Job(idempotency_key=key, run_id=run.id, request_json=marker, status='QUEUED',
                          created_at=self.managed._now(), activation_id=self.managed._admit(session, assessment),
                          language_context=self.managed._language(session, run.id))
                session.add(job)
                session.flush()
                run.status, run.stage, op.status, op.finished_at = 'QUEUED', 'bootstrap', 'QUEUED', None
                self.managed._event(session, run, 'bootstrap_resume_confirmed', {
                    'operation_id': op.id, 'job_id': job.id, 'reason': reason, 'actor': actor()})
                return _job(job)
            self._empty_authority(session, str(context.root))
            from my_harness.storage.planning import lock_for_bootstrap
            lock_for_bootstrap(session, shown)
            job = self.managed._queue_new_run(session, assessment, context, versions, 'P001-BOOTSTRAP',
                                             'P001', key, marker, purpose='bootstrap')
            session.add(Bootstrap(id=operation_id, root=str(context.root), run_id=job.run_id, status='QUEUED',
                phase_id=None, preview={k: v for k, v in shown.items() if k not in ('expected_version', 'resume_operation_id')},
                intent=intent, decision={'actor': actor(), 'reason': reason, 'confirmed': True},
                created_at=self.managed._now()))
            self.managed._event(session, session.get(Run, job.run_id), 'bootstrap_confirmed', {
                'operation_id': operation_id, 'preview_sha256': preview_sha256, 'intent': intent,
                'reason': reason, 'actor': actor()})
            return job
