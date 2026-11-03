"""Owner clarification of a settled task gap. Journal events remain append-only workflow authority."""
from datetime import datetime, timedelta
import json

from sqlalchemy import select

from my_harness.core.engine.knowledge import digest
from my_harness.storage.models import ManagedEventRow as Event, ManagedRunRow as Run
from my_harness.storage.permissions import PermissionRepository, actor
from my_harness.storage.managed import Conflict
from my_harness.i18n import tr


def invalid():
    raise Conflict(tr('managed.gap_resolution_invalid'))


class TaskGaps:
    def __init__(self, managed):
        self.managed = managed

    @staticmethod
    def latest(session, run_id):
        return session.scalar(select(Event).where(
            Event.run_id == run_id, Event.kind == 'task_decision_requested',
            Event.payload['kind'].as_string() == 'blocking_questions').order_by(Event.sequence.desc()).limit(1))

    def binding(self, session, run, history, source):
        cycle = history.cycles[-1]
        return {'source_attempt_id': source, 'review_cycle': cycle.number, 'kind': 'blocking_questions',
                'questions': json.loads(cycle.review_json)['blocking_questions'],
                'code_fingerprint': cycle.evidence.fingerprint,
                'context_sha256': digest(history.context_json), 'contract_sha256': digest(history.task_json),
                'documents': self.managed._task_document_binding(session, run.id)}

    def view(self, row):
        return {'event_id': row.id, 'run_id': row.run_id, 'kind': row.kind,
                'request_sha256': row.payload['request_sha256'],
                'expires_at': row.payload.get('expires_at')}

    def _event(self, session, run_id, event_id, kind):
        row = session.get(Event, event_id)
        if row is None or row.run_id != run_id or row.kind != kind:
            invalid()
        return row

    def _active(self, session, run, decision):
        gap = self.latest(session, run.id)
        payload = decision.payload
        if (gap is None or payload['gap_event_id'] != gap.id
                or payload['request_sha256'] != gap.payload.get('request_sha256')
                or payload['expires_at'] <= self.managed._now()
                or session.scalar(select(Event.id).where(Event.run_id == run.id,
                    Event.kind == 'task_gap_resolution_revoked',
                    Event.payload['resolution_id'].as_integer() == decision.id)) is not None):
            invalid()
        history = json.loads(run.history_json)['history']
        request = {key: value for key, value in gap.payload.items()
                   if key not in ('request_sha256', 'status', 'stage', 'revisions')}
        cycle = next((cycle for cycle in history['cycles'] if cycle['number'] == gap.payload['review_cycle']), None)
        source = next((attempt for attempt in history['attempts']
                       if attempt['request']['id'] == gap.payload['source_attempt_id']), None)
        if (digest(request) != gap.payload['request_sha256']
                or gap.payload['contract_sha256'] != digest(history['task_json'])
                or gap.payload['context_sha256'] != digest(run.context_json)
                or cycle is None or cycle['evidence']['fingerprint'] != gap.payload['code_fingerprint']
                or json.loads(cycle['review_json']).get('blocking_questions') != gap.payload['questions']
                or source is None or source['request']['role'] != 'reviewer'
                or gap.payload['documents'] != self.managed._task_document_binding(session, run.id)):
            invalid()
        self.managed._bound_task_delivery(session, run)
        return gap

    def answer(self, run_id, *, key, expected_version, gap_event_id, request_sha256, answers, ttl_seconds):
        request = locals().copy()
        del request['self']
        with self.managed._write() as session:
            prior = session.scalar(select(Event).where(
                Event.run_id == run_id, Event.kind == 'task_gap_resolved',
                Event.payload['key'].as_string() == key))
            if prior is not None:
                if prior.payload['request'] != request:
                    invalid()
                return self.view(prior)
            run = PermissionRepository(self.managed)._editable(session, run_id, expected_version)
            gap = self._event(session, run_id, gap_event_id, 'task_decision_requested')
            questions = gap.payload.get('questions')
            if (gap != self.latest(session, run_id) or request_sha256 != gap.payload.get('request_sha256')
                    or not isinstance(questions, list) or len(answers) != len(questions)
                    or not all(isinstance(q, str) and q.strip() for q in questions)
                    or not all(isinstance(a, str) and 0 < len(a.strip()) <= 4000 for a in answers)
                    or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400):
                invalid()
            if session.scalar(select(Event.id).where(Event.run_id == run_id, Event.kind == 'task_gap_resolved',
                    Event.payload['gap_event_id'].as_integer() == gap.id)) is not None:
                invalid()
            expires = datetime.fromisoformat(self.managed._now()) + timedelta(seconds=ttl_seconds)
            row = self.managed._event(session, run, 'task_gap_resolved', {
                'key': key, 'request': request, 'gap_event_id': gap.id, 'request_sha256': request_sha256,
                'resolution_kind': 'clarification', 'answers': answers, 'origin': 'owner_confirmed',
                'actor': actor(), 'expires_at': expires.isoformat(timespec='microseconds')})
            session.flush()
            self._active(session, run, row)
            return self.view(row)

    def revoke(self, run_id, resolution_id, *, expected_version, reason):
        if not reason.strip():
            invalid()
        with self.managed._write() as session:
            run = session.get(Run, run_id)
            if run is None or run.version != expected_version:
                invalid()
            decision = self._event(session, run_id, resolution_id, 'task_gap_resolved')
            if session.scalar(select(Event.id).where(Event.run_id == run_id,
                    Event.kind == 'task_gap_resolution_revoked',
                    Event.payload['resolution_id'].as_integer() == decision.id)) is None:
                self.managed._event(session, run, 'task_gap_resolution_revoked', {
                    'resolution_id': decision.id, 'request_sha256': decision.payload['request_sha256'],
                    'actor': actor(), 'reason': reason})
            return self.view(decision)

    def admit(self, session, run, resolution_id):
        gap = self.latest(session, run.id)
        if gap is None:
            if resolution_id is not None:
                invalid()
            return None
        # Old blocked cycles remain in history, but only the latest unresolved cycle requires a resolution.
        latest_cycle = json.loads(run.history_json)['history']['cycles'][-1]
        if gap.payload['review_cycle'] != latest_cycle['number']:
            if resolution_id is not None:
                invalid()
            return None
        if resolution_id is None:
            invalid()
        decision = self._event(session, run.id, resolution_id, 'task_gap_resolved')
        self._active(session, run, decision)
        if session.scalar(select(Event.id).where(Event.run_id == run.id,
                Event.kind == 'task_gap_resolution_applied',
                Event.payload['resolution_id'].as_integer() == decision.id)) is not None:
            invalid()
        return decision

    def check_acceptance(self, session, run):
        history = json.loads(run.history_json)['history']
        if not history['attempts']:
            return
        request = history['attempts'][-1]['request']
        snapshot = json.loads(request.get('prompt_snapshot_json') or '{}')
        marker = snapshot.get('task_gap_resolution')
        if marker is not None:
            decision = self._event(session, run.id, marker['resolution_id'], 'task_gap_resolved')
            self._active(session, run, decision)

    def for_job(self, session, run, job):
        identity = json.loads(job.request_json).get('gap_resolution_id')
        if identity is None:
            return None
        decision = self._event(session, run.id, identity, 'task_gap_resolved')
        gap = self._active(session, run, decision)
        return {'resolution_id': decision.id, 'gap_event_id': gap.id,
                'source_attempt_id': gap.payload['source_attempt_id'],
                'request_sha256': decision.payload['request_sha256'],
                'questions': gap.payload['questions'], 'answers': decision.payload['answers'],
                'code_fingerprint': gap.payload['code_fingerprint'],
                'origin': 'owner_confirmed'}
