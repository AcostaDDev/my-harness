"""Bootstrap proposal in the existing queue; does not decide or write documents.

D088: retired with the v1 creation; only reading recorded runs and their reconciliation remain."""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.storage.models import ManagedRunRow as Run, ManagedJobRow as Job, ManagedEventRow as Event


def settle(managed, session, run, outcome):
    managed._event(session, run, 'bootstrap_discovery_result', {'outcome': outcome})


def abort(managed, session, run, status, reason):
    managed._event(session, run, 'bootstrap_discovery_result', {'outcome': {
        'status': 'UNKNOWN', 'result': None, 'reason': reason}})


class DiscoveryRepository:
    def __init__(self, managed):
        self.managed = managed

    def latest(self, root):
        with Session(self.managed.engine) as session:
            run = session.scalar(select(Run).where(Run.root == str(root), Run.purpose == 'bootstrap_discovery')
                                 .order_by(Run.created_at.desc(), Run.id.desc()).limit(1))
            if run is None:
                return None
            event = session.scalar(select(Event).where(Event.run_id == run.id, Event.kind == 'bootstrap_discovery_result')
                                   .order_by(Event.sequence.desc()).limit(1))
            job = session.scalar(select(Job).where(Job.run_id == run.id))
            return {'run_id': run.id, 'run_status': run.status,
                    'brief': json.loads(job.request_json)['snapshot']['brief'],
                    'outcome': event.payload['outcome'] if event else None}

    def request(self, run_id):
        with Session(self.managed.engine) as session:
            row = session.scalar(select(Job).where(Job.run_id == run_id))
            return json.loads(row.request_json)['snapshot']

    def submit(self, context, brief, versions, writer, *, key, confirmed):
        """D088: the one-turn discovery only served the retired v1 creation. Runs already recorded
        are still read with `latest` and `request`; a new one is never admitted."""
        from my_harness.storage.bootstrap import V1_RETIRED
        from my_harness.i18n import tr
        raise ValueError(tr(V1_RETIRED))
