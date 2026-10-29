"""P002-T005 (D286): typed domain commands and queries with one shared validation pipeline.

API routes, deterministic graph nodes and (from T008) the tool broker all call `DomainOperations.execute` with a
catalogue reference. In order: catalogue entry and schema digest, arguments, caller principal/role/tool policy, then
inside one transaction query-only refusal, caller re-verification, project membership, idempotency, per-operation
capabilities, preconditions, the handler and the outcome record; audit sinks (T006 events and operations) run in the
outcome's transaction and in the separate refusal transaction. Missing infrastructure of later tasks fails closed:
agent callers (T008), permission state (T010) and delegated adoption (T016). T007 supplies the exact receipt sink.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from my_harness.core.engine import domain_policy as policy
from my_harness.core.engine import knowledge as core
from my_harness.core.engine import frozen_context as context_core
from my_harness.core.engine.contracts import ContractError, freeze
from my_harness.core.engine.domain_catalogue import CATALOGUE, MAX_ARGUMENTS, SchemaError, validate
from my_harness.i18n import tr
from my_harness.storage.knowledge import KnowledgeIntegrityError, KnowledgeSession, StaleRevision
from my_harness.storage.models import DomainCommandRow, KnowledgeProjectRow, KnowledgeRevisionRow
from my_harness.storage.permissions import actor as service_actor

CHANNELS = ('api', 'graph', 'internal', 'broker')
# HTTP status of each refusal code; every other code is 409.
STATUS = {'not_found': 404, 'project_unregistered': 404, 'revision_unknown': 404, 'operation_unknown': 422,
          'schema_mismatch': 422, 'arguments_invalid': 422, 'idempotency_key_required': 422,
          'knowledge_invalid': 422, 'caller_not_allowed': 403, 'capability_unavailable': 403,
          'capability_denied': 403, 'ceiling_excluded': 403, 'owner_only_excluded': 403, 'caller_unavailable': 403,
          'delegation_unavailable': 403, 'provenance_not_allowed': 403, 'receipts_unavailable': 403,
          'delivery_key_required': 422, 'delivery_over_limit': 422, 'cursor_invalid': 422}


def now() -> str:
    return datetime.now(UTC).isoformat()


class DomainRefusal(Exception):
    """A typed refusal; nothing of the refused call was written except, where possible, its audit row."""

    def __init__(self, code: str, **params):
        super().__init__(tr(f'domain.{code}', **params))
        self.code, self.params = code, params

    @property
    def status(self) -> int:
        return STATUS.get(self.code, 409)


@dataclass(frozen=True)
class Caller:
    """Bound by trusted infrastructure only; no operation argument can set any field (INV-11, TM04)."""
    principal: str
    channel: str
    knowledge_project_id: str | None = None  # reads, agents
    root: str | None = None  # mutations of owner and harness callers: the registered canonical root
    role: str | None = None
    invocation_id: str | None = None
    attempt_id: str | None = None
    thread_id: str | None = None
    operation_key: str | None = None
    frozen_revision_id: str | None = None
    tool_policy: frozenset = frozenset()

    @property
    def scope(self) -> str:
        if self.principal == 'owner':
            return 'owner'
        if self.principal == 'harness':
            return f'harness:{self.thread_id or "service"}'
        return f'invocation:{self.invocation_id}'

    def references(self) -> dict:
        return {name: value for name, value in (
            ('role', self.role), ('invocation_id', self.invocation_id), ('attempt_id', self.attempt_id),
            ('thread_id', self.thread_id), ('operation_key', self.operation_key),
            ('frozen_revision_id', self.frozen_revision_id)) if value is not None}

    def actor(self) -> dict:
        if self.principal == 'owner':
            return {'principal': 'owner', 'channel': self.channel, **service_actor()}
        return {'principal': self.principal, 'channel': self.channel, **self.references()}


def owner_reader(knowledge_project_id: str | None = None) -> Caller:
    """The local session holder reading persisted knowledge; no registered project or checkout is needed."""
    return Caller('owner', 'api', knowledge_project_id=knowledge_project_id)


def owner_writer(root: str) -> Caller:
    """The local session holder changing knowledge of a registered project (the API resolved `root`)."""
    return Caller('owner', 'api', root=root)


def harness_caller(root: str, *, channel: str = 'graph', thread_id: str | None = None,
                   operation_key: str | None = None) -> Caller:
    if channel not in ('graph', 'internal'):
        raise ValueError(tr('domain.channel', channel=channel))
    return Caller('harness', channel, root=root, thread_id=thread_id, operation_key=operation_key)


class CallerResolver(Protocol):
    def verify(self, session: Session, caller: Caller) -> None:
        """Re-verifies an agent caller against its persisted invocation inside the command's transaction."""


class PermissionProvider(Protocol):
    def state(self, session: Session, caller: Caller) -> policy.PermissionState | None:
        """Frozen snapshot, revocation and the frozen/current/role ceilings, read in the command's session."""


class AuthorizationProvider(Protocol):
    def state(self, session: Session, caller: Caller) -> policy.PermissionState | None:
        """The parent autonomous authorization's tiers for a delegated adoption (T016)."""


class DeliverySink(Protocol):
    def record(self, session: Session, caller: Caller, delivery: Mapping) -> None:
        """Persists knowledge-access receipts in the query's transaction (T007)."""


class UnavailableResolver:
    def verify(self, session, caller):
        raise DomainRefusal('caller_unavailable')


class UnavailablePermissions:
    def state(self, session, caller):
        return None


class NoAuthorizations:
    def state(self, session, caller):
        return None


@dataclass(frozen=True)
class Outcome:
    operation: str
    result: Mapping
    command_id: str | None = None
    replayed: bool = False

    def body(self) -> dict:
        if self.command_id is None:
            return dict(self.result)
        return {**self.result, 'command_id': self.command_id, 'replayed': self.replayed}


@dataclass
class _Call:
    """Per-call state shared by `execute` and the handler."""
    service: 'DomainOperations'
    session: Session
    caller: Caller
    entry: object
    arguments: Mapping
    project_id: str | None
    knowledge: KnowledgeSession
    origin: str | None = None
    capability: Mapping | None = None
    draft_id: str | None = None
    revision_id: str | None = None
    delivery: Mapping | None = None

    def authorize(self, product_targets=()) -> None:
        """Evaluates the entry's requirements and the call's `product` targets; handlers call it before writing."""
        requirements = [('tools', self.entry.tool_target), *(('product', t) for t in sorted(set(product_targets)))]
        principal = self.caller.principal
        if principal == 'owner':
            basis = {'authority': 'owner'}
        elif principal == 'harness':
            basis = {'authority': 'harness_internal'}  # query and propose only; adoption is refused before
        else:
            decision = policy.evaluate(requirements, self.service.permissions.state(self.session, self.caller))
            if not decision.allowed:
                raise DomainRefusal(decision.code, layer=decision.layer or '')
            basis = decision.basis
        self.capability = {'requirements': [list(r) for r in requirements], **basis}


class DomainOperations:
    def __init__(self, engine, *, resolver: CallerResolver | None = None,
                 permissions: PermissionProvider | None = None,
                 authorizations: AuthorizationProvider | None = None, delivery: DeliverySink | None = None,
                 audit_sinks: tuple[Callable, ...] = (), catalogue=CATALOGUE):
        self.engine = engine
        self.resolver = resolver or UnavailableResolver()
        self.permissions = permissions or UnavailablePermissions()
        self.authorizations = authorizations or NoAuthorizations()
        self.delivery = delivery
        self.audit_sinks = audit_sinks
        self.catalogue = catalogue
        self.handlers = {
            'knowledge.projects': self._projects, 'knowledge.head': self._head, 'knowledge.list': self._list,
            'knowledge.get': self._get, 'knowledge.draft.get': self._draft_get,
            'knowledge.draft.open': self._draft_open, 'knowledge.draft.apply': self._draft_apply,
            'knowledge.draft.discard': self._draft_discard, 'knowledge.adoption.preview': self._preview,
            'knowledge.adopt': self._adopt,
            'knowledge.lookup': self._lookup, 'knowledge.search': self._search,
        }

    # Discovery for the broker (T008) -------------------------------------------------------------------------------

    def scoped(self, caller: Caller):
        return self.catalogue.scoped(caller.principal, caller.role, caller.tool_policy)

    def describe(self, caller: Caller, operation_id: str, version: int):
        entry = self.catalogue.get(operation_id, version)
        if entry is None or entry not in self.scoped(caller):
            raise DomainRefusal('operation_unknown', operation=operation_id)
        return entry

    # Pipeline ------------------------------------------------------------------------------------------------------

    def execute(self, caller: Caller, ref, arguments: Mapping, key: str | None = None) -> Outcome:
        operation_id, version, schema_sha256 = ref
        entry = self.catalogue.get(operation_id, version)
        try:
            if caller.channel not in CHANNELS or caller.principal not in ('owner', 'harness', 'agent'):
                raise DomainRefusal('caller_not_allowed')
            if entry is None or (operation_id, version) in self.catalogue.retired:
                raise DomainRefusal('operation_unknown', operation=operation_id)
            if schema_sha256 != entry.schema_sha256:
                raise DomainRefusal('schema_mismatch', operation=operation_id)
            try:
                if len(freeze(arguments).encode('utf-8')) > MAX_ARGUMENTS:
                    raise SchemaError('$', 'size')
                validate(entry.input, arguments)
            except (SchemaError, TypeError, ValueError) as error:
                raise DomainRefusal('arguments_invalid', where=getattr(error, 'path', '$')) from None
            if caller.principal not in entry.principals or caller.principal == 'agent' and (
                    caller.role not in entry.roles or entry.ref not in caller.tool_policy):
                raise DomainRefusal('caller_not_allowed')
            if entry.mutates and (not isinstance(key, str) or not key.strip() or len(key) > 200):
                raise DomainRefusal('idempotency_key_required')
            if caller.principal == 'agent' and not entry.mutates and self.delivery is None:
                raise DomainRefusal('receipts_unavailable')
            return self._transaction(caller, entry, arguments, key)
        except DomainRefusal as refusal:
            if entry is None or entry.mutates or caller.principal == 'agent':
                self._record_refusal(caller, entry, operation_id, version, arguments, key, refusal)
            raise

    def _transaction(self, caller, entry, arguments, key) -> Outcome:
        writes = entry.mutates or caller.principal == 'agent'
        with Session(self.engine) as session, session.begin():
            knowledge = KnowledgeSession(session)
            if writes:
                if session.execute(text('PRAGMA query_only')).scalar():
                    raise DomainRefusal('query_only')
                session.execute(text('DELETE FROM domain_commands WHERE 0'))  # write lock before any read
            if caller.principal == 'agent':
                self.resolver.verify(session, caller)
            project_id = self._project(session, knowledge, caller, entry)
            call = _Call(self, session, caller, entry, arguments, project_id, knowledge)
            call.origin = 'owner_confirmed' if entry.kind == 'adopt' and caller.principal == 'owner' else None
            request_sha256 = policy.request_sha256(entry, arguments, call.origin)
            if caller.principal == 'agent' and not entry.mutates and hasattr(self.delivery, 'replay'):
                call.authorize()
                replay = self.delivery.replay(session, caller, key, request_sha256)
                if replay is not None:
                    return Outcome(entry.id, replay, replayed=True)
            if entry.mutates and project_id is not None:
                previous = session.scalar(select(DomainCommandRow).where(
                    DomainCommandRow.knowledge_project_id == project_id, DomainCommandRow.scope == caller.scope,
                    DomainCommandRow.idempotency_key == key, DomainCommandRow.outcome == 'ACCEPTED'))
                if previous is not None:
                    if previous.request_sha256 != request_sha256:
                        raise DomainRefusal('idempotency_conflict')
                    return Outcome(entry.id, previous.result, previous.command_id, True)
            try:
                result = self.handlers[entry.id](call)
            except StaleRevision:
                raise DomainRefusal('stale_revision') from None
            except (ContractError, ValueError) as error:
                raise DomainRefusal('knowledge_invalid', detail=str(error)) from None
            except KnowledgeIntegrityError:
                raise DomainRefusal('knowledge_integrity') from None
            if call.capability is None:
                raise RuntimeError(tr('domain.unauthorized_handler', operation=entry.id))
            validate(entry.output, result)
            if caller.principal == 'agent' and not entry.mutates:
                self.delivery.record(session, caller, {**(call.delivery or {}), 'result': result, 'key': key,
                                                       'request_sha256': request_sha256})
            if not entry.mutates:
                return Outcome(entry.id, result)
            row = DomainCommandRow(
                command_id=str(uuid4()), knowledge_project_id=project_id, operation_id=entry.id,
                operation_version=entry.version, schema_sha256=entry.schema_sha256,
                catalogue_sha256=self.catalogue.sha256, principal=caller.principal, channel=caller.channel,
                caller=caller.references(), actor=caller.actor(), origin=call.origin, scope=caller.scope,
                idempotency_key=key, request_sha256=request_sha256, outcome='ACCEPTED', capability=call.capability,
                result=result, draft_id=call.draft_id, revision_id=call.revision_id, recorded_at=now())
            session.add(row)
            session.flush()
            for sink in self.audit_sinks:
                sink(session, row)
            return Outcome(entry.id, result, row.command_id, False)

    def _record_refusal(self, caller, entry, operation_id, version, arguments, key, refusal) -> None:
        if refusal.code == 'query_only':
            return
        try:
            request = policy.request_sha256(entry, arguments, None) if entry is not None else None
        except (TypeError, ValueError):
            request = None
        try:
            with Session(self.engine) as session, session.begin():
                if session.execute(text('PRAGMA query_only')).scalar():
                    return
                project = caller.knowledge_project_id or (
                    KnowledgeSession(session).project_id(caller.root) if caller.root else None)
                if project is not None and session.get(KnowledgeProjectRow, project) is None:
                    project = None
                row = DomainCommandRow(
                    command_id=str(uuid4()), knowledge_project_id=project, operation_id=str(operation_id)[:80],
                    operation_version=version if isinstance(version, int) else 0,
                    schema_sha256=entry.schema_sha256 if entry else None, catalogue_sha256=self.catalogue.sha256,
                    principal=caller.principal, channel=caller.channel, caller=caller.references(),
                    actor=caller.actor(), origin=None, scope=caller.scope[:200],
                    idempotency_key=key[:200] if isinstance(key, str) else None, request_sha256=request,
                    outcome='REFUSED', refusal_code=refusal.code, capability=None, result=None,
                    recorded_at=now())
                session.add(row)
                session.flush()
                for sink in self.audit_sinks:  # T006: the refusal event shares the refusal's own transaction
                    sink(session, row)
                if (caller.principal == 'agent' and entry is not None and not entry.mutates and request
                        and refusal.code in ('not_found', 'revision_outside_context', 'cursor_invalid',
                                             'delivery_over_limit', 'knowledge_invalid', 'knowledge_integrity')
                        and hasattr(self.delivery, 'failure')):
                    self.delivery.failure(session, caller, key, request, refusal.code)
        except Exception as error:  # noqa: BLE001  (a refusal never becomes a success; report the audit failure)
            raise RuntimeError(tr('domain.refusal_unrecorded', code=refusal.code)) from error

    def _project(self, session, knowledge, caller, entry) -> str | None:
        if entry.id == 'knowledge.projects':
            return None
        if caller.knowledge_project_id is not None:
            if session.get(KnowledgeProjectRow, caller.knowledge_project_id) is None:
                raise DomainRefusal('not_found')
            return caller.knowledge_project_id
        if caller.root is None:
            raise DomainRefusal('not_found')
        found = knowledge.project_id(caller.root)
        if found is None and entry.id == 'knowledge.draft.open':
            return knowledge.create_project(caller.root)
        if found is None and entry.mutates:
            raise DomainRefusal('not_found')
        return found

    # Shared reads --------------------------------------------------------------------------------------------------

    def _frozen(self, call):
        """The agent's frozen accepted revision, verified; never the head (§4 of the T005 record)."""
        row = call.session.get(KnowledgeRevisionRow, call.caller.frozen_revision_id or '')
        if row is None or row.project_id != call.project_id or row.status != 'ACCEPTED':
            raise DomainRefusal('not_found')
        return call.knowledge.revision(call.project_id, row.number)

    def _revision(self, call, number):
        """Owner/harness: `number` or the head (None without revisions). Agents: only their frozen revision."""
        if call.caller.principal == 'agent':
            frozen = self._frozen(call)
            if number is not None and number != frozen.number:
                raise DomainRefusal('revision_outside_context')
            return frozen
        if call.project_id is None:
            if number is not None:
                raise DomainRefusal('revision_unknown', number=number)
            return None
        try:
            if number is None:
                head = call.knowledge.head(call.project_id)
                return call.knowledge.revision(call.project_id, head.number) if head else None
            return call.knowledge.revision(call.project_id, number)
        except LookupError:
            raise DomainRefusal('revision_unknown', number=number) from None

    @staticmethod
    def _summary(revision) -> dict | None:
        if revision is None:
            return None
        counts = {}
        for member in revision.members.values():
            name = policy.group(member.kind, member.document)
            counts[name] = counts.get(name, 0) + 1
        return {'id': revision.id, 'number': revision.number, 'revision_sha256': revision.revision_sha256,
                'knowledge_sha256': revision.knowledge_sha256, 'origin': revision.origin,
                'accepted_at': revision.accepted_at, 'counts': dict(sorted(counts.items()))}

    @staticmethod
    def _member(member) -> dict:
        return {'item_id': member.item_id, 'kind': member.kind, 'document': member.document, 'code': member.code,
                'version': member.version, 'content_sha256': member.content_sha256, 'content': member.content,
                'provenance': member.provenance, 'source': member.source, 'root_position': member.root_position}

    @staticmethod
    def _link(link) -> dict:
        return {'kind': link.kind, 'source_item_id': link.source, 'target_item_id': link.target,
                'position': link.position, 'qualifier': link.qualifier}

    def _owned_draft(self, call, *, edit: bool):
        """The draft row of this project, attributed to its opener; non-openers other than the owner see nothing."""
        draft = call.session.get(KnowledgeRevisionRow, call.arguments['draft_id'])
        if draft is None or draft.project_id != call.project_id:
            raise DomainRefusal('not_found')
        if call.caller.principal == 'agent' and draft.status == 'ACCEPTED' and draft.id != call.caller.frozen_revision_id:
            raise DomainRefusal('not_found')
        opener = call.session.scalar(select(DomainCommandRow).where(
            DomainCommandRow.draft_id == draft.id, DomainCommandRow.operation_id == 'knowledge.draft.open',
            DomainCommandRow.outcome == 'ACCEPTED'))
        if opener is None:
            raise DomainRefusal('draft_unattributed')
        if opener.scope != call.caller.scope:
            if call.caller.principal != 'owner':
                raise DomainRefusal('not_found')
            if edit:
                raise DomainRefusal('draft_not_owned')
        return draft, opener

    def _draft_sha256(self, call, draft_id):
        members, links = call.knowledge.manifest(draft_id)
        return core.knowledge_sha256(call.project_id, members.values(), links), members, links

    # Handlers ------------------------------------------------------------------------------------------------------

    def _lookup(self, call):
        call.authorize()
        args = call.arguments
        revision = self._revision(call, args.get('revision'))
        member = revision.members.get(args['item_id']) if revision else None
        if member is None:
            raise DomainRefusal('not_found')
        budget = args.get('max_bytes', 8192)
        while True:
            e = context_core.exposure(member, level=args.get('exposure', 'full'), start=args.get('start', 0),
                                      length=args.get('length', 2048), budget=budget)
            result = {'revision': {'id': revision.id, 'number': revision.number, 'revision_sha256': revision.revision_sha256},
                      'exposures': [e], 'page': {'truncated': e['truncated'], 'total': 1,
                                               'limit': 1, 'max_bytes': args.get('max_bytes', 8192)}}
            if len(freeze(result).encode('utf-8')) <= context_core.MAX_RESULT:
                return result
            budget //= 2

    def _search(self, call):
        call.authorize()
        args = call.arguments
        revision = self._revision(call, args.get('revision'))
        if revision is None:
            raise DomainRefusal('not_found')
        fingerprint = context_core.digest(freeze({'revision_id': revision.id,
            'arguments': {k: v for k, v in args.items() if k != 'cursor'}}))
        offset = 0
        if 'cursor' in args:
            try:
                position, sha = args['cursor'].split(':')
                offset = int(position)
                if offset < 0 or sha != fingerprint or str(offset) != position:
                    raise ValueError()
            except ValueError:
                raise DomainRefusal('cursor_invalid') from None
        query = args['query'].casefold()
        # Search verified accepted members only; no global SQL index can leak another revision/project.
        selected = sorted((m for m in revision.members.values()
            if args.get('kind') in (None, m.kind) and ('document' not in args or args['document'] == m.document)
            and query in (m.code + '\n' + freeze(m.content)).casefold()), key=lambda m: (m.kind, m.document or '', m.code))
        budget, used, exposures = args.get('max_bytes', 8192), 0, []
        for member in selected[offset:offset + args.get('limit', 20)]:
            e = context_core.exposure(member, level=args.get('exposure', 'metadata'), budget=max(0, budget - used))
            size = len(e['data'].encode('utf-8'))
            if exposures and used + size + len(freeze(e['identity']).encode('utf-8')) > budget:
                break
            if len(freeze(exposures + [e]).encode('utf-8')) > context_core.MAX_RESULT - 1024:
                if exposures:
                    break
                e = context_core.exposure(member, level=args.get('exposure', 'metadata'), budget=min(16384, budget))
                size = len(e['data'].encode('utf-8'))
            exposures.append(e)
            used += size + len(freeze(e['identity']).encode('utf-8'))
            if used >= budget:
                break
        end = offset + len(exposures)
        page = {'truncated': end < len(selected), 'total': len(selected), 'page': offset,
                'limit': args.get('limit', 20), 'max_bytes': budget}
        if end < len(selected):
            page['next_cursor'] = f'{end}:{fingerprint}'
        return {'revision': {'id': revision.id, 'number': revision.number, 'revision_sha256': revision.revision_sha256},
                'exposures': exposures, 'page': page}

    def _projects(self, call):
        call.authorize()
        offset, limit = call.arguments.get('offset', 0), call.arguments.get('limit', 50)
        session = call.session
        total = session.scalar(select(func.count()).select_from(KnowledgeProjectRow))
        items = []
        for row in session.scalars(select(KnowledgeProjectRow).order_by(KnowledgeProjectRow.root, KnowledgeProjectRow.id)
                                   .offset(offset).limit(limit)):
            head = call.knowledge.head(row.id)
            items.append({'id': row.id, 'root': row.root, 'head': None if head is None else {
                'number': head.number, 'revision_sha256': head.revision_sha256}})
        return {'items': items, 'total': total, 'offset': offset, 'limit': limit}

    def _head(self, call):
        call.authorize()
        revision = self._revision(call, None)
        call.delivery = {'channel': 'query', 'operation': call.entry.id, 'exposure': 'metadata',
                         'revision_id': revision.id if revision else None, 'items': []}
        return {'knowledge_project_id': call.project_id, 'revision': self._summary(revision)}

    def _list(self, call):
        call.authorize()
        arguments = call.arguments
        revision = self._revision(call, arguments.get('revision'))
        if revision is None:
            raise DomainRefusal('revision_unknown', number=arguments.get('revision'))
        selected = sorted((m for m in revision.members.values()
                           if arguments.get('kind') in (None, m.kind)
                           and ('document' not in arguments or arguments['document'] == m.document)),
                          key=lambda m: (m.kind, m.document or '', m.code))
        offset, limit = arguments.get('offset', 0), arguments.get('limit', 50)
        page = selected[offset:offset + limit]
        items = [{'item_id': m.item_id, 'kind': m.kind, 'document': m.document, 'code': m.code,
                  'version': m.version, 'content_sha256': m.content_sha256, 'title': m.content.get('title'),
                  'status': m.content['status']} for m in page]
        call.delivery = {'channel': 'query', 'operation': call.entry.id, 'exposure': 'metadata',
                         'revision_id': revision.id, 'items': [[m.item_id, m.content_sha256] for m in page],
                         'offset': offset, 'limit': limit, 'total': len(selected),
                         'truncated': offset + limit < len(selected)}
        return {'revision': {'id': revision.id, 'number': revision.number, 'revision_sha256': revision.revision_sha256},
                'items': items, 'total': len(selected), 'offset': offset, 'limit': limit, 'delivery': call.delivery}

    def _get(self, call):
        call.authorize()
        revision = self._revision(call, call.arguments.get('revision'))
        member = revision.members.get(call.arguments['item_id']) if revision else None
        if member is None:
            raise DomainRefusal('not_found')
        links = [self._link(l) for l in sorted(revision.links, key=core.Link.key)
                 if member.item_id in (l.source, l.target)]
        call.delivery = {'channel': 'query', 'operation': call.entry.id, 'exposure': 'full',
                         'revision_id': revision.id, 'items': [[member.item_id, member.content_sha256]]}
        return {'revision': {'id': revision.id, 'number': revision.number, 'revision_sha256': revision.revision_sha256},
                'item': self._member(member), 'links': links, 'delivery': call.delivery}

    def _draft_get(self, call):
        call.authorize()
        draft, opener = self._owned_draft(call, edit=False)
        sha, members, links = self._draft_sha256(call, draft.id)
        call.delivery = {'channel': 'query', 'operation': call.entry.id, 'exposure': 'full', 'draft_id': draft.id,
                         'items': sorted([m.item_id, m.content_sha256] for m in members.values())}
        return {'draft_id': draft.id, 'status': draft.status, 'base_revision_id': draft.base_revision_id,
                'draft_sha256': sha, 'opener': {'principal': opener.principal, **{
                    k: v for k, v in opener.caller.items() if k in ('role', 'invocation_id', 'thread_id')}},
                'members': [self._member(m) for m in sorted(members.values(), key=lambda m: (m.kind, m.code))],
                'links': [self._link(l) for l in sorted(links, key=core.Link.key)]}

    def _draft_open(self, call):
        call.authorize()
        call.knowledge.writable()
        expected = call.arguments['expected_revision_id']
        if call.caller.principal == 'agent':
            frozen = self._frozen(call)
            if expected != frozen.id:
                raise DomainRefusal('revision_outside_context')
            base = frozen.id
        else:
            head = call.knowledge.head(call.project_id)
            if expected != (head.id if head else None):
                raise DomainRefusal('stale_revision')
            base = expected
        draft = call.knowledge.open_draft(call.project_id, base)
        call.draft_id = draft
        sha, _members, _links = self._draft_sha256(call, draft)
        return {'knowledge_project_id': call.project_id, 'draft_id': draft, 'base_revision_id': base,
                'draft_sha256': sha}

    def _draft_apply(self, call):
        draft, _opener = self._owned_draft(call, edit=True)
        if draft.status != 'DRAFT':
            raise DomainRefusal('draft_not_open')
        sha, members, _links = self._draft_sha256(call, draft.id)
        if sha != call.arguments['expected_draft_sha256']:
            raise DomainRefusal('draft_changed')
        groups = set()
        for change in call.arguments['changes']:
            if change['op'] == 'put':
                groups.add(policy.group(change['kind'], change.get('document')))
                if not policy.provenance_allowed(call.caller.principal, change['provenance'], change.get('source')):
                    raise DomainRefusal('provenance_not_allowed')
            else:
                for name in ('item_id', 'source_item_id', 'target_item_id'):
                    if name in change:
                        member = members.get(change[name])
                        if member is None:
                            raise DomainRefusal('not_found')
                        groups.add(policy.group(member.kind, member.document))
        call.authorize(f'knowledge.propose:{name}' for name in groups)
        call.knowledge.writable()
        item_ids = []
        for change in call.arguments['changes']:
            op = change['op']
            if op == 'put':
                item_ids.append(call.knowledge.put(
                    draft.id, change['kind'], change['code'], change['content'], document=change.get('document'),
                    provenance=change['provenance'], source=change.get('source'),
                    root_position=change.get('root_position')))
                members = call.knowledge.manifest(draft.id)[0]
            elif op == 'remove':
                if change['item_id'] not in members:
                    raise DomainRefusal('not_found')
                call.knowledge.remove(draft.id, change['item_id'])
                members.pop(change['item_id'])
            else:
                if change['source_item_id'] not in members or change['target_item_id'] not in members:
                    raise DomainRefusal('not_found')
                if op == 'link':
                    call.knowledge.link(draft.id, change['kind'], change['source_item_id'], change['target_item_id'],
                                        position=change.get('position'), qualifier=change.get('qualifier'))
                else:
                    call.knowledge.unlink(draft.id, change['kind'], change['source_item_id'],
                                          change['target_item_id'])
        call.draft_id = draft.id
        sha, _members, _links = self._draft_sha256(call, draft.id)
        return {'draft_id': draft.id, 'draft_sha256': sha, 'item_ids': item_ids}

    def _draft_discard(self, call):
        draft, _opener = self._owned_draft(call, edit=False)
        if draft.status != 'DRAFT':
            raise DomainRefusal('draft_not_open')
        call.authorize()
        call.knowledge.writable()
        call.knowledge.discard(draft.id)
        call.draft_id = draft.id
        return {'draft_id': draft.id, 'status': 'DISCARDED'}

    def _preview_of(self, call):
        draft, _opener = self._owned_draft(call, edit=False)
        if draft.status != 'DRAFT':
            raise DomainRefusal('draft_not_open')
        head = call.knowledge.head(call.project_id)
        if draft.base_revision_id != (head.id if head else None):
            raise DomainRefusal('stale_revision')
        sha, members, links = self._draft_sha256(call, draft.id)
        previous = call.knowledge.manifest_dict(head.id) if head else None
        core.validate_revision(members, links, previous, adoption=True)
        if head is not None and sha == head.knowledge_sha256:
            raise DomainRefusal('empty_adoption')
        changes = core.change_summary(members, links, previous)
        classification = policy.classify(members, links, previous)
        base_sha = head.revision_sha256 if head else None
        return {'draft_id': draft.id, 'base_revision_id': draft.base_revision_id, 'base_revision_sha256': base_sha,
                'draft_sha256': sha, 'changes': changes, 'classification': classification,
                'reason_required': policy.reason_required(classification),
                'preview_sha256': policy.preview_sha256(call.project_id, draft.id, draft.base_revision_id, base_sha,
                                                        sha, changes, classification)}

    def _preview(self, call):
        call.authorize()
        return self._preview_of(call)

    def _adopt(self, call):
        if call.caller.principal != 'owner':
            # `owner_delegated` needs the parent authorization of T016 and `harness_deterministic` a named rule;
            # neither exists in T005 (empty rule registry), so no other principal can adopt.
            raise DomainRefusal('delegation_unavailable')
        arguments = call.arguments
        head = call.knowledge.head(call.project_id)
        if arguments['expected_revision_id'] != (head.id if head else None):
            raise DomainRefusal('stale_revision')
        preview = self._preview_of(call)
        if preview['preview_sha256'] != arguments['preview_sha256']:
            raise DomainRefusal('preview_stale')
        reason = arguments.get('reason')
        if preview['reason_required'] and not (reason or '').strip():
            raise DomainRefusal('reason_required')
        call.authorize(f'knowledge.adopt:{name}' for name in policy.classes(preview['classification']))
        call.knowledge.writable()
        try:
            revision = call.knowledge.adopt(preview['draft_id'], arguments['expected_revision_id'],
                                            origin=call.origin, actor=call.caller.actor(), reason=reason)
        except StaleRevision:
            raise DomainRefusal('stale_revision') from None
        call.draft_id = call.revision_id = revision.id
        return {'revision_id': revision.id, 'number': revision.number, 'revision_sha256': revision.revision_sha256,
                'knowledge_sha256': revision.knowledge_sha256, 'origin': revision.origin, 'changes': revision.changes}
