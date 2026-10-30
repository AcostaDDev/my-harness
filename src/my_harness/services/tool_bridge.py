"""Invocation-bound broker. The stdio child never opens a database; services stay in the supervisor."""
from dataclasses import asdict
import json
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from my_harness.core.engine import tool_bridge as core
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.domain_catalogue import SchemaError, digest, validate
from my_harness.services.domain_operations import Caller, DomainOperations, DomainRefusal
from my_harness.storage.frozen_context import ReceiptSink, bound, delivery_data, persist
from my_harness.storage.models import (ManagedAttemptRow, ManagedJobRow, ManagedRunRow, UsageInvocationRow,
                                       KnowledgeDeliveryRow, CheckoutLockRow)
from my_harness.storage.operation_journal import now, record_event, record_envelope
from my_harness.i18n import tr


class InvocationResolver:
    """Rechecks all persisted bindings and the live fenced writer, also on idempotent replay."""
    def __init__(self, catalogue=None):
        from my_harness.core.engine.domain_catalogue import CATALOGUE
        self.catalogue = catalogue or CATALOGUE

    def resolve(self, session, attempt_id):
        attempt = session.get(ManagedAttemptRow, attempt_id)
        if attempt is None:
            raise DomainRefusal('caller_unavailable')
        request = json.loads(attempt.request_json)
        marker, refs = core.selection(request, catalogue=self.catalogue)
        invocation = session.scalar(select(UsageInvocationRow).where(UsageInvocationRow.attempt_id == attempt_id))
        if invocation is None:
            raise DomainRefusal('caller_unavailable')
        boundary, snapshot, context, operation = bound(session, invocation.id)
        run = session.get(ManagedRunRow, attempt.run_id)
        job = session.get(ManagedJobRow, operation.job_id)
        lock = session.get(CheckoutLockRow, operation.root)
        versions = json.loads(attempt.versions_json)
        role = marker['role']
        if (attempt.status != 'ACTIVE' or attempt.result_json is not None or operation.kind != 'agent_invocation'
                or operation.status != 'INTENDED' or operation.refs.get('role') != request['role']
                or operation.attempt_id != attempt.id or operation.invocation_id != invocation.id
                or boundary.attempt_id != attempt.id or invocation.source_kind != 'managed_attempt'
                or invocation.source_id != attempt.id or invocation.run_id != attempt.run_id
                or invocation.role != request['role'] or run is None or run.root != operation.root
                or invocation.root != operation.root or request['context_json'] != run.context_json
                or job is None or job.run_id != run.id or job.status != 'ACTIVE' or job.owner_closed
                or job.owner_token != operation.owner_token or not job.lease_until or job.lease_until <= now()
                or lock is None or lock.job_id != job.id
                or versions.get(f'{role}_provider') != marker['client']
                or versions.get(f'{role}_cli') != marker['version']
                or context['client'] != marker['client']):
            raise DomainRefusal('caller_unavailable')
        return Caller('agent', 'broker', knowledge_project_id=snapshot.project_id, root=operation.root,
                      role=role, invocation_id=invocation.id, attempt_id=attempt.id,
                      thread_id=operation.thread_id, operation_key=operation.key,
                      frozen_revision_id=snapshot.revision_id, tool_policy=refs)

    def verify(self, session, caller):
        try:
            expected = self.resolve(session, caller.attempt_id)
        except (ValueError, TypeError, KeyError):
            raise DomainRefusal('caller_unavailable') from None
        if caller != expected:
            raise DomainRefusal('caller_unavailable')


class Broker:
    def __init__(self, operations, caller):
        self.operations, self.caller = operations, caller

    def event(self, session, kind, key, payload, *, parent=None):
        # Serialize with the process journal before reading the context/event chain. SQLite cannot upgrade
        # an older WAL read snapshot after another writer commits, regardless of busy_timeout.
        session.execute(text('DELETE FROM domain_commands WHERE 0'))
        c = self.caller
        return record_event(session, kind=kind, dedupe_key=key, payload=payload, root=c.root,
                            thread_id=c.thread_id, operation_id=self._operation(session).id,
                            invocation_id=c.invocation_id, parent_event_id=parent)

    def _operation(self, session):
        return bound(session, self.caller.invocation_id)[3]

    def _verify(self, session):
        if session.execute(text('PRAGMA query_only')).scalar():
            raise DomainRefusal('query_only')
        session.execute(text('DELETE FROM domain_commands WHERE 0'))
        self.operations.resolver.verify(session, self.caller)

    def _discovery(self, name, args):
        c = self.caller
        request_hash = digest({'broker': name, 'arguments': args})
        with Session(self.operations.engine) as session, session.begin():
            self._verify(session)
            key = 'broker:' + args['key']
            previous = session.scalar(select(KnowledgeDeliveryRow).where(
                KnowledgeDeliveryRow.invocation_id == c.invocation_id, KnowledgeDeliveryRow.key == key))
            if previous is not None:
                if previous.request_sha256 != request_hash:
                    raise DomainRefusal('idempotency_conflict')
                return delivery_data(previous)['result']
            entries = sorted(self.operations.scoped(c), key=lambda e: (e.id, e.version))
            scope_hash = digest([e.ref for e in entries])
            common = {'format': 'tool-discovery-1', 'invocation_id': c.invocation_id,
                      'catalogue_sha256': scope_hash}
            if name == 'search_tools':
                query = args.get('query', '')
                candidates = [e for e in entries if query.casefold() in (e.id + ' ' + e.summary).casefold()]
                fingerprint = digest({'scope': scope_hash, 'invocation': c.invocation_id,
                                      'query': query, 'limit': args.get('limit', 20)})
                offset = 0
                if 'cursor' in args:
                    try:
                        position, sha = args['cursor'].split(':')
                        offset = int(position)
                        if sha != fingerprint or offset < 0 or offset >= len(candidates):
                            raise ValueError
                    except ValueError:
                        raise DomainRefusal('cursor_invalid') from None
                selected = candidates[offset:offset + args.get('limit', 20)]
                end = offset + len(selected)
                page = {'truncated': end < len(candidates), 'total': len(candidates),
                        'next_cursor': f'{end}:{fingerprint}' if end < len(candidates) else None}
                result = {'items': [core.descriptor(e) for e in selected], 'page': page}
                envelope = {**common, 'action': 'search', 'query_sha256': digest(query),
                            'query_length': len(query), 'page': page,
                            'results': [{k: v for k, v in e.items() if k in ('id', 'version', 'schema_sha256')}
                                        for e in result['items']]}
            else:
                entry = self.operations.describe(c, args['id'], args['version'])
                result = {**entry.document(), 'schema_sha256': entry.schema_sha256}
                envelope = {**common, 'action': 'describe', 'id': entry.id, 'version': entry.version,
                            'schema_sha256': entry.schema_sha256, 'outcome': 'delivered'}
            if len(freeze(result).encode()) > core.MAX_RESPONSE:
                raise DomainRefusal('delivery_over_limit')
            operation = self._operation(session)
            record_envelope(session, 'tool.discovered', envelope, dedupe_key=f'bridge:discovery:{uuid4()}',
                            root=c.root, thread_id=c.thread_id, operation_id=operation.id,
                            invocation_id=c.invocation_id)
            # Exact descriptor/schema bytes are response evidence, never project knowledge or model comprehension.
            persist(session, c.invocation_id, key, request_hash, 'tool_result', result,
                    [{'identity': {'kind': 'result', 'item_id': c.frozen_revision_id},
                      'authority': 'response', 'data': freeze(result), 'exposure': 'full'}])
            return result

    def call(self, name, arguments):
        call_id = str(uuid4())
        parent = None
        try:
            with Session(self.operations.engine) as session, session.begin():
                self._verify(session)
                event = self.event(session, 'broker.called', f'broker:call:{call_id}',
                                   {'broker': name[:80] if isinstance(name, str) else 'invalid',
                                    'arguments_sha256': digest(arguments), 'call_id': call_id})
                parent = event.event_id
            tool = next((t for t in core.TOOLS if t['name'] == name), None)
            if tool is None:
                raise DomainRefusal('operation_unknown', operation='broker')
            try:
                validate(tool['inputSchema'], arguments)
            except (SchemaError, TypeError, ValueError):
                raise DomainRefusal('arguments_invalid', where='$') from None
            if name == 'invoke_tool':
                ref = arguments['id'], arguments['version'], arguments['schema_sha256']
                # Do not let the generic envelope disclose or bypass the frozen scope.
                self.operations.describe(self.caller, ref[0], ref[1])
                with Session(self.operations.engine) as session, session.begin():
                    self._verify(session)
                    self.event(session, 'tool.called', f'logical:call:{call_id}',
                               {'id': ref[0], 'version': ref[1], 'schema_sha256': ref[2],
                                'key_sha256': digest(arguments['key'])}, parent=parent)
                outcome = self.operations.execute(self.caller, ref, arguments['arguments'], arguments['key'])
                body = outcome.body()
                if outcome.command_id:
                    body.pop('replayed', None)  # replay observation is outside the stable domain response
                result = {'ok': True, 'operation': ref[0], 'result': body, 'replayed': outcome.replayed}
            else:
                result = {'ok': True, 'result': self._discovery(name, arguments)}
        except DomainRefusal as refusal:
            result = {'ok': False, 'error': {'code': refusal.code}}
        except (ValueError, TypeError, KeyError):
            result = {'ok': False, 'error': {'code': 'arguments_invalid'}}
        # Persistence failure propagates; unrecorded content must never be returned to the pipe.
        if parent:
            with Session(self.operations.engine) as session, session.begin():
                session.execute(text('DELETE FROM domain_commands WHERE 0'))
                if name == 'invoke_tool' and result['ok'] and outcome.command_id:
                    # Commands already committed their effect/outcome. Persist the stable response before return;
                    # a crash in between re-enters execute, rechecks authority and never repeats that effect.
                    ReceiptSink('tool_result').record(session, self.caller,
                        {'result': result['result'], 'key': 'mutation:' + digest(arguments['key']),
                         'request_sha256': digest({'ref': ref, 'arguments': arguments['arguments']})})
                if name == 'invoke_tool':
                    self.event(session, 'tool.result', f'logical:result:{call_id}',
                               {'id': arguments.get('id') if isinstance(arguments, dict) else None,
                                'ok': result['ok'], 'error': result.get('error'),
                                'result_sha256': digest(result), 'replayed': result.get('replayed'),
                                'command_id': outcome.command_id if result['ok'] else None}, parent=parent)
                self.event(session, 'broker.result', f'broker:result:{call_id}',
                           {'call_id': call_id, 'broker': name, 'ok': result['ok'],
                            'operation': arguments.get('id') if isinstance(arguments, dict) else None,
                            'result_sha256': digest(result), 'error': result.get('error')}, parent=parent)
        return result


class BridgeFactory:
    """Explicit adapter binding; legacy paths never create a bridge. Tests inject synthetic permissions/cells."""
    def __init__(self, operations, *, qualifications=core.NATIVE):
        if getattr(operations.delivery, 'channel', None) != 'tool_result':
            raise ValueError(tr('bridge.policy'))
        self.operations, self.qualifications = operations, qualifications

    def open(self, request, config, directory):
        from my_harness.adapters.tool_bridge_transport import BridgeSession
        marker, _ = core.selection(asdict(request), catalogue=self.operations.catalogue)
        cell = core.qualification(self.qualifications, config.provider, config.cli_version, marker['role'],
                                  marker['evidence'])
        if marker['provenance'] != cell.provenance:
            raise ValueError(tr('bridge.provenance'))
        resolver = self.operations.resolver
        with Session(self.operations.engine) as session:
            caller = resolver.resolve(session, request.id)
            if session.get(ManagedAttemptRow, request.id).request_json != freeze(asdict(request)):
                raise DomainRefusal('caller_unavailable')
        return BridgeSession(Broker(self.operations, caller), directory)
