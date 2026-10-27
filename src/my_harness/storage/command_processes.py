"""Command process projection of the existing durable job journal (no second queue)."""
import json

from sqlalchemy import select

from my_harness.storage.models import ManagedEventRow


PREFIX = 'command_process_'


def project(events):
    records = {}
    for kind, payload in events:
        key = payload['command_id']
        if kind == PREFIX + 'intent':
            records[key] = {'command_id': key, 'job_id': payload['job_id'],
                            'spec': payload['spec'], 'identity': None, 'capture': None, 'status': 'PENDING'}
        elif kind == PREFIX + 'spawned':
            records[key]['identity'] = payload['identity']
            records[key]['status'] = 'RUNNING'
        elif kind == PREFIX + 'finished':
            records[key]['capture'] = payload['capture']
            records[key]['status'] = 'STOPPED' if payload['capture']['group_state'] == 'dead' else 'UNCERTAIN'
    return list(records.values())


def for_job(session, job):
    rows = session.scalars(select(ManagedEventRow).where(
        ManagedEventRow.run_id == job.run_id,
        ManagedEventRow.kind.in_([PREFIX + name for name in ('intent', 'spawned', 'finished')])
    ).order_by(ManagedEventRow.sequence))
    return project((row.kind, row.payload) for row in rows if row.payload['job_id'] == job.id)


def persisted_identities(db):
    """sqlite3 maintenance readers use the same ownership evidence, including old jobs."""
    for row in db.execute("SELECT payload FROM managed_events WHERE kind='command_process_spawned'"):
        yield json.loads(row[0])['identity']
    # Preparation commands have a real preparation owner in the shared process table, never a run event.
    for row in db.execute('SELECT identity FROM managed_processes WHERE preparation_id IS NOT NULL AND identity IS NOT NULL'):
        yield json.loads(row[0])
