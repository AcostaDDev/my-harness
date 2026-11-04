"""P002-T016 (D300): reviewer jobs of autonomous runs over the existing managed queue, ledger and supervisor.

Two kinds: the G12 readiness gap report of one frozen revision and the delegated execution contract of one accepted
task. Each is an ordinary managed job (purpose `autonomy`, action `roadmap_review`) with an idempotency key bound to
its frozen inputs; its settlement seals the validated result once in `autonomous_reviews`. An operational failure
records an event only and is never requeued automatically.
"""
import json
from uuid import uuid4

from sqlalchemy import select

from my_harness.core.engine import autonomy
from my_harness.core.engine.contracts import freeze
from my_harness.storage.managed import _job
from my_harness.storage.models import (AutonomousReviewRow as Review, KnowledgeProjectRow, ManagedJobRow as Job,
                                       ManagedRunRow as Run)
from my_harness.storage import autonomous_runs as store

ACTION = 'roadmap_review'
PURPOSE = 'autonomy'


def readiness_key(root, revision, version, attempt=0):
    return f'roadmap-readiness:{autonomy.digest([str(root), revision["id"], version, attempt])[:48]}'


def task_plan_key(root, task, version_sha256, attempt):
    return f'roadmap-task-plan:{autonomy.digest([str(root), task, version_sha256, attempt])[:48]}'


def queue(managed, context, versions, *, kind, key, payload, phase_id):
    request = freeze({'action': ACTION, 'kind': kind, **payload})
    assessment = managed.guard.assess(context.root)
    with managed._write() as session:
        existing = managed._existing(session, key, request)
        if existing:
            return _job(existing)
        label = payload.get('task_id') or 'ROADMAP-READINESS'
        return managed._queue_new_run(session, assessment, context, versions, label, phase_id, key, request,
                                      purpose=PURPOSE)


def job(session, key):
    return session.scalar(select(Job).where(Job.idempotency_key == key))


def task_plan(session, root, task, version_sha256):
    """The latest sealed delegated contract proposal of this exact accepted task version, if any."""
    return session.scalar(select(Review).where(Review.root == str(root), Review.kind == 'task_plan',
                                               Review.gap_sha256 == autonomy.digest([task, version_sha256]))
                          .order_by(Review.created_at.desc(), Review.id.desc()).limit(1))


def _request(session, run):
    row = session.scalar(select(Job).where(Job.run_id == run.id).order_by(Job.id.desc()).limit(1))
    return json.loads(row.request_json), row


def settle(managed, session, run, outcome):
    request, row = _request(session, run)
    project = session.scalar(select(KnowledgeProjectRow.id).where(KnowledgeProjectRow.root == run.root))
    status = outcome.get('status')
    managed._event(session, run, 'autonomy_review_result', {'kind': request['kind'], 'review_status': status,
                                                            'reason': outcome.get('reason')})
    if status not in ('REPORTED', 'MALFORMED', 'PROPOSED', 'REFUSED'):
        return  # operational failure: evidence only, never sealed or retried by the harness
    now = managed._now()
    if request['kind'] == 'readiness':
        payload = ({'status': 'reported', 'report': outcome['result'], 'readiness_version': request['version'],
                    'job_id': row.id} if status == 'REPORTED'
                   else {'status': 'malformed', 'readiness_version': request['version'], 'job_id': row.id})
        store.seal_gap_report(session, root=run.root, project=project, revision=request['revision'],
                              readiness_version=request['version'], payload=payload, now=now)
        return
    payload = {'status': status.lower(), 'task_id': request['task_id'], 'phase_id': request['phase_id'],
               'version_sha256': request['version_sha256'], 'job_id': row.id,
               **({'contract': outcome['result'], 'plan_text': outcome['plan_text'],
                   'contract_sha256': outcome['contract_sha256']} if status == 'PROPOSED'
                  else {'reason': outcome.get('reason')})}
    session.add(Review(id=str(uuid4()), root=run.root, project_id=project, kind='task_plan',
                       record_key=f'task_plan:{row.idempotency_key}', revision_id=request['revision']['id'],
                       revision_sha256=request['revision']['sha256'],
                       gap_sha256=autonomy.digest([request['task_id'], request['version_sha256']]), payload=payload,
                       sha256=autonomy.digest(payload), origin='harness_deterministic',
                       actor={'principal': 'harness'}, created_at=now))
    session.flush()


def abort(managed, session, run, status, reason):
    request, _ = _request(session, run)
    managed._event(session, run, 'autonomy_review_result', {'kind': request['kind'], 'review_status': status,
                                                            'reason': reason})
