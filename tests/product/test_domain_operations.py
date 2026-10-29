"""P002-T005 (D286): typed domain operations, capability policy and outcome records.

Synthetic knowledge on temporary SQLite migrated to head, the real service, repository and graph runner. The agent
resolver, permission provider and receipt sink below are test-only doubles; the product composition has none of
them. No model, CLI, Git, network or real project. Evidence E01–E12, E14–E19 and E21 of the T005 record; controls
TM01–TM05 (with TM12 support for graph replay).
"""
import ast
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest
from sqlalchemy import text

from my_harness.core.engine import domain_policy as policy
from my_harness.core.engine import knowledge as core
from my_harness.core.engine.domain_catalogue import (
    CATALOGUE, RESERVED, Catalogue, SchemaError, lint, validate,
)
from my_harness.core.engine.permissions import LAYERS
from my_harness.services.domain_operations import (
    Caller, DomainOperations, DomainRefusal, NoAuthorizations, UnavailablePermissions, UnavailableResolver,
    harness_caller, owner_reader, owner_writer,
)
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.storage.database import make_engine

SOURCE = Path(__file__).resolve().parents[2] / 'src/my_harness'
ROOT = '/synthetic/project'
OTHER = '/synthetic/other'
OWNER = owner_writer(ROOT)
KNOWLEDGE_TABLES = ('knowledge_projects', 'knowledge_items', 'knowledge_item_versions', 'knowledge_revisions',
                    'knowledge_revision_members', 'knowledge_revision_links', 'domain_commands')
# Pinned digests: any change of an entry's schema, principals, roles or capabilities changes its digest (TM02).
DIGESTS = {
    'knowledge.lookup': '18c8e98fa6b9183ffded177aecb88fcd0a60044eb95dc1c0ca19122349b0ad72',
    'knowledge.search': 'ccb4717d970cee6219a28a748da7ffc8ecd5b251337a44ad72c741d3538f020b',
    'knowledge.projects': '75b0e3fc4dfcb89e99ad93a2eae6e7d25b5db128cc7265408b0dea9316ff8479',
    'knowledge.head': '269624f8a42153135b20e360436a81999d52c28d8760489daa2b541a5181edb7',
    'knowledge.list': 'fb379035692863f6a7e8aea1ba504a1cd5069344a00a5be248e74e4545ca01c8',
    'knowledge.get': '066e73b65f4ebf646325ffe7fd2882e233889e60f70e2b35e7df47c92aa6d8b8',
    'knowledge.draft.get': '4ba6a7a3d8db141304cd0b91418d98e7359109d7fe21eeabf6688d9ba6d88f07',
    'knowledge.draft.open': '400f4fba047b9e9247c7262e4cacc876383f2e0ac20c5f93fb323ee5d6daf073',
    'knowledge.draft.apply': '7364631107abb3e73ea9a3db2a2d027e2cee69e11d61871a2a0eb2f726b25f03',
    'knowledge.draft.discard': '5aa8bcbaa5a32d70e5894cb443a9c243d52fddcb885b0982465f83a86df9632b',
    'knowledge.adoption.preview': 'e576cd9adc2fc5238c31a72dcd285d842d34759c99d3a4ca605f6e8fa2cced82',
    'knowledge.adopt': '830135167089eb188ae8eac7bced444d872f837546ccf1c0dcea463b2fd49043',
}


def requirement(statement='Users can sign in.'):
    return {'title': 'Sign in', 'statement': statement, 'status': 'active'}


def criterion(statement='A wrong password is refused.'):
    return {'statement': statement, 'status': 'active'}


def phase(objective='Deliver sign in.', title='Accounts'):
    return {'title': title, 'objective': objective, 'tag': None, 'status': 'planned'}


def task(title='Login form'):
    return {'title': title, 'problem': 'No login.', 'expected_result': 'A login form.', 'subtasks': ['Form'],
            'evidence': '', 'status': 'planned'}


def decision(title='Use sessions', status='accepted'):
    return {'title': title, 'context': '', 'decision': 'Server sessions.', 'alternatives': '', 'consequences': '',
            'status': status, 'historical_status': None}


def section(title, body, target='agents'):
    return {'title': title, 'format': 'markdown', 'body': body, 'target': target, 'status': 'active'}


def put(kind, code, content, **extra):
    return {'op': 'put', 'kind': kind, 'code': code, 'content': content, 'provenance': 'known', **extra}


def ref(operation):
    return CATALOGUE.current(operation).ref


def run(ops, caller, operation, arguments, key=None):
    return ops.execute(caller, ref(operation), arguments, key)


def refused(code, action):
    with pytest.raises(DomainRefusal) as caught:
        action()
    assert caught.value.code == code, caught.value.code
    return caught.value


def rows(url, table, where=''):
    with closing(sqlite3.connect(url.removeprefix('sqlite:///'))) as db:
        return db.execute(f'SELECT * FROM {table} {where} ORDER BY 1').fetchall()


def snapshot(url):
    return {table: rows(url, table) for table in KNOWLEDGE_TABLES}


def accepted(url):
    return rows(url, 'domain_commands', "WHERE outcome = 'ACCEPTED'")


class Session:
    """Opens, edits, previews and adopts drafts through the service, as one principal."""

    def __init__(self, ops, caller, prefix):
        self.ops, self.caller, self.prefix, self.count = ops, caller, prefix, 0

    def key(self):
        self.count += 1
        return f'{self.prefix}-{self.count}'

    def open(self, expected):
        result = run(self.ops, self.caller, 'knowledge.draft.open', {'expected_revision_id': expected}, self.key())
        return result.result['draft_id'], result.result['draft_sha256']

    def apply(self, draft, sha, changes):
        result = run(self.ops, self.caller, 'knowledge.draft.apply',
                     {'draft_id': draft, 'expected_draft_sha256': sha, 'changes': changes}, self.key())
        return result.result['draft_sha256'], result.result['item_ids']


def adopt(ops, draft, expected, reason='Synthetic owner adoption.', key=None):
    preview = run(ops, OWNER, 'knowledge.adoption.preview', {'draft_id': draft}).result
    return run(ops, OWNER, 'knowledge.adopt', {'draft_id': draft, 'expected_revision_id': expected,
                                               'preview_sha256': preview['preview_sha256'], 'reason': reason},
               key or f'adopt-{draft}').result


def seed(ops, root=ROOT):
    """Revision 1: R001 with C001, P001 addressing R001 with task P001-T001, decision D001, architecture section."""
    owner = Session(ops, owner_writer(root), f'seed-{root}')
    draft, sha = owner.open(None)
    sha, (r, c, p, t, d, s) = owner.apply(draft, sha, [
        put('requirement', 'R001', requirement()), put('criterion', 'C001', criterion()),
        put('phase', 'P001', phase()), put('task', 'P001-T001', task()), put('decision', 'D001', decision()),
        put('section', 'overview', section('Overview', 'Text.'), document='architecture', root_position=0)])
    owner.apply(draft, sha, [
        {'op': 'link', 'kind': 'criterion_of', 'source_item_id': c, 'target_item_id': r, 'position': 0},
        {'op': 'link', 'kind': 'part_of', 'source_item_id': t, 'target_item_id': p, 'position': 0},
        {'op': 'link', 'kind': 'addresses', 'source_item_id': p, 'target_item_id': r}])
    preview = run(ops, owner_writer(root), 'knowledge.adoption.preview', {'draft_id': draft}).result
    revision = run(ops, owner_writer(root), 'knowledge.adopt', {
        'draft_id': draft, 'expected_revision_id': None, 'preview_sha256': preview['preview_sha256'],
        'reason': 'First revision.'}, f'seed-adopt-{root}').result
    return {'R001': r, 'C001': c, 'P001': p, 'T001': t, 'D001': d, 'overview': s}, revision


# Test-only doubles. None of them exists in `src/`; the product composition refuses agents (E03).

class TrustingResolver:
    def __init__(self):
        self.sessions = []

    def verify(self, session, caller):
        self.sessions.append(session)


class SyntheticReceipts:
    def __init__(self):
        self.records = []

    def record(self, session, caller, delivery):
        assert session.in_transaction()
        self.records.append((caller.invocation_id, delivery))


class TablePermissions:
    """Grants and ceilings in tables this test creates, read through the command's session."""

    def __init__(self, engine):
        self.engine, self.sessions, self.fail = engine, [], False
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE test_grants (grant_id TEXT, dimension TEXT, target TEXT, '
                                    'revoked INTEGER DEFAULT 0)'))
            connection.execute(text('CREATE TABLE test_ceilings (copy TEXT, layer TEXT, dimension TEXT, target TEXT)'))
        self.hook = None

    def grant(self, dimension, target, grant_id=None, ceilings=True):
        with self.engine.begin() as connection:
            connection.execute(text('INSERT INTO test_grants VALUES (:g, :d, :t, 0)'),
                               {'g': grant_id or f'g-{dimension}-{target}', 'd': dimension, 't': target})
            if ceilings:
                for copy in ('frozen', 'current'):
                    for layer in LAYERS:
                        self.ceiling(copy, layer, dimension, target, connection)
                self.ceiling('role', 'role', dimension, target, connection)

    def ceiling(self, copy, layer, dimension, target, connection=None):
        statement = text('INSERT INTO test_ceilings VALUES (:c, :l, :d, :t)')
        values = {'c': copy, 'l': layer, 'd': dimension, 't': target}
        if connection is None:
            with self.engine.begin() as connection:
                connection.execute(statement, values)
        else:
            connection.execute(statement, values)

    def drop(self, copy, layer, target):
        with self.engine.begin() as connection:
            connection.execute(text('DELETE FROM test_ceilings WHERE copy = :c AND layer = :l AND target = :t'),
                               {'c': copy, 'l': layer, 't': target})

    def revoke(self, target):
        with self.engine.begin() as connection:
            connection.execute(text('UPDATE test_grants SET revoked = 1 WHERE target = :t'), {'t': target})

    def allow(self, *operations, product=()):
        for operation in operations:
            self.grant('tools', CATALOGUE.current(operation).tool_target)
        for target in product:
            self.grant('product', target)

    def state(self, session, caller):
        self.sessions.append(session)
        if self.hook is not None:
            self.hook(session)
        if self.fail:
            raise RuntimeError('synthetic provider failure')
        grants = session.execute(text('SELECT grant_id, dimension, target, revoked FROM test_grants')).all()
        authority = {'frozen': {}, 'current': {}, 'role': {}}
        for copy, layer, dimension, target in session.execute(text('SELECT * FROM test_ceilings')):
            authority[copy].setdefault(layer, {}).setdefault(dimension, set()).add(target)
        return policy.PermissionState(
            snapshot_sha256='0' * 64, grants=tuple((g, d, t) for g, d, t, _r in grants),
            unavailable=frozenset(g for g, _d, _t, r in grants if r), frozen_authority=authority['frozen'],
            current_authority=authority['current'], role_ceiling=authority['role'].get('role', {}))


def agent(project, frozen, *, role='reviewer', invocation='inv-1', operations=None):
    entries = CATALOGUE if operations is None else [CATALOGUE.current(o) for o in operations]
    return Caller('agent', 'broker', knowledge_project_id=project, role=role, invocation_id=invocation,
                  attempt_id=f'{invocation}-a1', frozen_revision_id=frozen,
                  tool_policy=frozenset(entry.ref for entry in entries))


@pytest.fixture
def world(migrated_database):
    url = migrated_database[0]
    engine = make_engine(url)
    yield url, engine, DomainOperations(engine)
    engine.dispose()


@pytest.fixture
def agents(world):
    url, engine, _ops = world
    permissions = TablePermissions(engine)
    receipts = SyntheticReceipts()
    ops = DomainOperations(engine, resolver=TrustingResolver(), permissions=permissions, delivery=receipts)
    return ops, permissions, receipts


# Catalogue (E04, E05) ----------------------------------------------------------------------------------------------

def test_catalogue_entries_are_pinned_closed_and_free_of_caller_fields():
    assert {entry.id: entry.schema_sha256 for entry in CATALOGUE} == DIGESTS
    for entry in CATALOGUE:
        assert lint(entry.input) == [] and lint(entry.output) == []
        assert entry.kind in ('query', 'propose', 'adopt') and entry.version == 1
        assert ('agent' in entry.principals) == bool(entry.roles)
        assert entry.id.startswith('knowledge.')  # no SQL, file, code or effect entry exists
    assert 'agent' not in CATALOGUE.current('knowledge.adopt').principals
    assert 'agent' not in CATALOGUE.current('knowledge.adoption.preview').principals
    assert lint({'type': 'object', 'properties': {'project_id': {'type': 'string'}}, 'additionalProperties': False})
    assert lint({'type': 'object', 'properties': {}})  # an object must state its closure


def test_schema_digest_unknown_and_retired_versions_are_refused_without_fallback(world):
    url, engine, ops = world
    entry = CATALOGUE.current('knowledge.draft.open')
    before = snapshot(url)
    refused('schema_mismatch', lambda: ops.execute(OWNER, (entry.id, 1, '0' * 64), {'expected_revision_id': None},
                                                   'k'))
    refused('operation_unknown', lambda: ops.execute(OWNER, (entry.id, 2, entry.schema_sha256),
                                                     {'expected_revision_id': None}, 'k'))
    retired = DomainOperations(engine, catalogue=Catalogue(list(CATALOGUE), retired={(entry.id, 1)}))
    refused('operation_unknown', lambda: retired.execute(OWNER, entry.ref, {'expected_revision_id': None}, 'k'))
    assert snapshot(url)['knowledge_revisions'] == before['knowledge_revisions']
    assert [row[16] for row in rows(url, 'domain_commands')] == ['schema_mismatch', 'operation_unknown',
                                                                 'operation_unknown']


def test_schema_validator_covers_the_subset_used():
    schema = CATALOGUE.current('knowledge.draft.apply').input
    good = {'draft_id': 'd', 'expected_draft_sha256': 'a' * 64, 'changes': [{'op': 'remove', 'item_id': 'i'}]}
    validate(schema, good)
    for bad in ({**good, 'changes': []}, {**good, 'expected_draft_sha256': 'x'}, {**good, 'draft_id': 7},
                {**good, 'changes': [{'op': 'remove', 'item_id': 'i', 'extra': 1}]},
                {**good, 'changes': [{'op': 'drop', 'item_id': 'i'}]}, {**good, 'changes': [{'op': 'remove'}]}):
        with pytest.raises(SchemaError):
            validate(schema, bad)
    with pytest.raises(SchemaError):
        validate({'type': 'integer'}, True)  # a boolean is not an integer


# Caller binding and project membership (E01–E03) -------------------------------------------------------------------

MINIMAL = {
    'knowledge.lookup': {'item_id': 'i'}, 'knowledge.search': {'query': 'x'},
    'knowledge.projects': {}, 'knowledge.head': {}, 'knowledge.list': {}, 'knowledge.get': {'item_id': 'i'},
    'knowledge.draft.get': {'draft_id': 'd'}, 'knowledge.draft.open': {'expected_revision_id': None},
    'knowledge.draft.apply': {'draft_id': 'd', 'expected_draft_sha256': 'a' * 64,
                              'changes': [{'op': 'remove', 'item_id': 'i'}]},
    'knowledge.draft.discard': {'draft_id': 'd'}, 'knowledge.adoption.preview': {'draft_id': 'd'},
    'knowledge.adopt': {'draft_id': 'd', 'expected_revision_id': None, 'preview_sha256': 'a' * 64},
}


def test_caller_fields_in_arguments_are_refused_for_every_entry(world):
    url, _engine, ops = world
    assert set(MINIMAL) == {entry.id for entry in CATALOGUE}
    before = snapshot(url)['knowledge_revisions']
    for entry in CATALOGUE:
        for name in sorted(RESERVED):
            refused('arguments_invalid',
                    lambda: ops.execute(OWNER, entry.ref, {**MINIMAL[entry.id], name: 'forged'}, 'k'))
    assert snapshot(url)['knowledge_revisions'] == before


def test_foreign_identifiers_are_indistinguishable_from_missing_ones(world):
    url, _engine, ops = world
    ids, first = seed(ops)
    other_ids, other = seed(ops, OTHER)
    owner_b = Session(ops, owner_writer(OTHER), 'b')
    foreign_draft, _sha = owner_b.open(other['revision_id'])
    project = run(ops, OWNER, 'knowledge.head', {}).result['knowledge_project_id']
    reader = owner_reader(project)
    before = snapshot(url)
    bodies = set()
    for missing in (other_ids['R001'], 'absent-id'):
        bodies.add(str(refused('not_found', lambda: run(ops, reader, 'knowledge.get',
                                                        {'revision': 1, 'item_id': missing}))))
    for missing in (foreign_draft, 'absent-draft'):
        bodies.add(str(refused('not_found', lambda: run(ops, reader, 'knowledge.draft.get', {'draft_id': missing}))))
        bodies.add(str(refused('not_found', lambda: run(ops, OWNER, 'knowledge.draft.discard',
                                                        {'draft_id': missing}, f'd-{missing}'))))
        bodies.add(str(refused('not_found', lambda: run(ops, OWNER, 'knowledge.adoption.preview',
                                                        {'draft_id': missing}))))
    draft, sha = Session(ops, OWNER, 'a').open(first['revision_id'])
    before = snapshot(url)
    for foreign in (other_ids['R001'], 'absent-id'):
        refused('not_found', lambda: run(ops, OWNER, 'knowledge.draft.apply', {
            'draft_id': draft, 'expected_draft_sha256': sha,
            'changes': [{'op': 'link', 'kind': 'addresses', 'source_item_id': ids['T001'],
                         'target_item_id': foreign}]}, f'l-{foreign}'))
    assert len(bodies) == 1  # one body for foreign and missing identifiers
    after = snapshot(url)
    assert {t: after[t] for t in KNOWLEDGE_TABLES[:-1]} == {t: before[t] for t in KNOWLEDGE_TABLES[:-1]}


def test_agent_callers_fail_closed_in_the_product_composition(world):
    url, engine, _ops = world
    ids, first = seed(DomainOperations(engine))
    product = ManagedRuntime(engine).domain_operations()
    assert isinstance(product.resolver, UnavailableResolver)
    assert isinstance(product.permissions, UnavailablePermissions)
    from my_harness.storage.frozen_context import ReceiptSink
    assert isinstance(product.authorizations, NoAuthorizations) and isinstance(product.delivery, ReceiptSink)
    project = run(product, OWNER, 'knowledge.head', {}).result['knowledge_project_id']
    caller = agent(project, first['revision_id'])
    before = snapshot(url)['knowledge_revisions']
    refused('caller_unavailable', lambda: run(product, caller, 'knowledge.head', {}))
    refused('caller_unavailable', lambda: run(product, caller, 'knowledge.draft.open',
                                              {'expected_revision_id': first['revision_id']}, 'a'))
    trusting = DomainOperations(engine, resolver=TrustingResolver())
    refused('capability_unavailable', lambda: run(trusting, caller, 'knowledge.draft.open',
                                                  {'expected_revision_id': first['revision_id']}, 'a'))
    assert snapshot(url)['knowledge_revisions'] == before
    test_doubles = ('TrustingResolver', 'TablePermissions', 'SyntheticReceipts')
    for path in SOURCE.rglob('*.py'):
        assert not any(name in path.read_text() for name in test_doubles), path


def test_only_the_service_mutates_knowledge_in_product_code():
    allowed = {'storage/knowledge.py', 'services/domain_operations.py', 'storage/frozen_context.py'}
    for path in SOURCE.rglob('*.py'):
        relative = path.relative_to(SOURCE).as_posix()
        names = {node.id for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.Name)}
        names |= {alias.name for node in ast.walk(ast.parse(path.read_text()))
                  if isinstance(node, ast.ImportFrom) for alias in node.names}
        if relative not in allowed:
            assert not names & {'KnowledgeRepository', 'KnowledgeSession'}, relative
    handlers = DomainOperations(None).handlers
    assert set(handlers) == {entry.id for entry in CATALOGUE}


# Roles, tool policy and adoption (E06, E07) -----------------------------------------------------------------------

def test_role_and_tool_policy_limit_what_an_agent_may_attempt(world, agents):
    url, _engine, _ops = world
    ops, permissions, _receipts = agents
    ids, first = seed(ops)
    project = run(ops, OWNER, 'knowledge.head', {}).result['knowledge_project_id']
    permissions.allow(*(entry.id for entry in CATALOGUE))
    frozen = first['revision_id']
    refused('caller_not_allowed', lambda: run(ops, agent(project, frozen, role='executor'), 'knowledge.draft.open',
                                              {'expected_revision_id': frozen}, 'e'))
    refused('caller_not_allowed', lambda: run(ops, agent(project, frozen, role='judge'), 'knowledge.head', {}))
    refused('caller_not_allowed', lambda: run(ops, agent(project, frozen, operations=['knowledge.list']),
                                              'knowledge.head', {}))
    for operation in ('knowledge.adopt', 'knowledge.adoption.preview', 'knowledge.projects'):
        refused('caller_not_allowed', lambda: run(ops, agent(project, frozen), operation, MINIMAL[operation], 'x'))
    assert run(ops, agent(project, frozen, role='executor'), 'knowledge.head', {}).result['revision']['number'] == 1
    assert [row[16] for row in rows(url, 'domain_commands', "WHERE outcome = 'REFUSED'")] == ['caller_not_allowed'] * 6


def test_only_the_owner_adopts_and_proposals_keep_their_author(world, agents):
    url, _engine, _ops = world
    ops, permissions, _receipts = agents
    ids, first = seed(ops)
    project = run(ops, OWNER, 'knowledge.head', {}).result['knowledge_project_id']
    frozen = first['revision_id']
    reviewer = agent(project, frozen)
    permissions.allow('knowledge.draft.open', 'knowledge.draft.apply', 'knowledge.draft.get',
                      product=['knowledge.propose:task', 'knowledge.propose:phase'])
    proposer = Session(ops, reviewer, 'agent')
    draft, sha = proposer.open(frozen)
    proposer.apply(draft, sha, [{**put('task', 'P001-T002', task('Logout')), 'provenance': 'inferred'}])
    refused('caller_not_allowed', lambda: run(ops, reviewer, 'knowledge.adopt', {
        'draft_id': draft, 'expected_revision_id': frozen, 'preview_sha256': 'a' * 64}, 'self'))
    harness = harness_caller(ROOT, channel='internal')
    refused('delegation_unavailable', lambda: run(ops, harness, 'knowledge.adopt', {
        'draft_id': draft, 'expected_revision_id': frozen, 'preview_sha256': 'a' * 64}, 'h'))
    refused('draft_not_owned', lambda: run(ops, OWNER, 'knowledge.draft.apply', {
        'draft_id': draft, 'expected_draft_sha256': 'a' * 64,
        'changes': [put('task', 'P001-T003', task())]}, 'owner-edit'))
    # The new task has no phase yet: the owner sees the invalid proposal instead of adopting it.
    refused('knowledge_invalid', lambda: run(ops, OWNER, 'knowledge.adoption.preview', {'draft_id': draft}))
    proposer.apply(draft, run(ops, reviewer, 'knowledge.draft.get', {'draft_id': draft}).result['draft_sha256'],
                   [{'op': 'link', 'kind': 'part_of', 'source_item_id': proposer_item(ops, reviewer, draft, 'P001-T002'),
                     'target_item_id': ids['P001'], 'position': 1}])
    revision = adopt(ops, draft, frozen, reason=None)
    assert revision['origin'] == 'owner_confirmed' and revision['number'] == 2
    opened, = [row for row in accepted(url) if row[3] == 'knowledge.draft.open' and row[19] == draft]
    adopted, = [row for row in accepted(url) if row[3] == 'knowledge.adopt' and row[20] == revision['revision_id']]
    assert opened[7] == 'agent' and adopted[7] == 'owner' and adopted[11] == 'owner_confirmed'
    with closing(sqlite3.connect(url.removeprefix('sqlite:///'))) as db:
        actor, = db.execute('SELECT actor FROM knowledge_revisions WHERE id = ?', (revision['revision_id'],)).fetchone()
    assert '"principal":"owner"' in actor.replace(' ', '')


def proposer_item(ops, caller, draft, code):
    members = run(ops, caller, 'knowledge.draft.get', {'draft_id': draft}).result['members']
    return next(m['item_id'] for m in members if m['code'] == code)


# Sensitivity and owner-only exclusion (E08) ------------------------------------------------------------------------

def member(item_id, kind, code, version=1, document=None, root=None, **content):
    defaults = {'requirement': requirement(), 'criterion': criterion(), 'phase': phase(), 'task': task(),
                'decision': decision(), 'section': section('S', 'B', content.pop('target', 'agents'))}[kind]
    body = {**defaults, **content}
    return core.Member(item_id, kind, document, code, version, f'{item_id}-{version}', body, 'known', None, root)


def link(kind, source, target, position=None, qualifier=None):
    return core.Link(kind, source, target, position, qualifier)


BASE = {
    'r': member('r', 'requirement', 'R001'), 'c': member('c', 'criterion', 'C001'), 'p': member('p', 'phase', 'P001'),
    't': member('t', 'task', 'P001-T001'), 'tc': member('tc', 'criterion', 'C002'),
    'd': member('d', 'decision', 'D001'), 'i': member('i', 'section', 'rules', document='instructions', root=0),
    'i2': member('i2', 'section', 'tools', document='instructions', root=1),
    's': member('s', 'section', 'overview', document='architecture', root=0),
}
BASE_LINKS = (link('criterion_of', 'c', 'r', 0), link('part_of', 't', 'p', 0), link('addresses', 'p', 'r'),
              link('criterion_of', 'tc', 't', 0), link('addresses', 't', 'r'))


def classified(members=None, links=None, add=(), add_links=()):
    members = dict(BASE if members is None else members)
    members.update({m.item_id: m for m in add})
    return policy.classify(members, tuple(links if links is not None else BASE_LINKS) + tuple(add_links),
                           {'members': BASE, 'links': BASE_LINKS})


def only(entries):
    assert len(entries) >= 1
    return {(e['class'], e['sensitive']) for e in entries}


@pytest.mark.parametrize('change, expected', [
    ('requirement changed', {('owner_only', True)}),
    ('criterion of requirement changed', {('owner_only', True)}),
    ('criterion of existing task changed', {('owner_only', True)}),
    ('criterion reordered', {('owner_only', True)}),
    ('criterion re-owned', {('owner_only', True)}),
    ('phase added', {('owner_only', True)}),
    ('phase objective changed', {('owner_only', True)}),
    ('phase withdrawn', {('owner_only', True)}),
    ('phase addresses', {('owner_only', True)}),
    ('instructions target', {('owner_only', True)}),
    ('instructions root order', {('owner_only', True)}),
    ('instructions parent', {('owner_only', True)}),
    ('decision superseded', {('owner_only', True), ('product', True)}),
    ('new task with criterion', {('planning', True), ('planning', False)}),
    ('new decision', {('product', True)}),
    ('architecture section', {('product', False)}),
    ('task planning', {('planning', False)}),
])
def test_every_change_has_a_class_and_a_sensitivity(change, expected):
    edit = {
        'requirement changed': lambda: classified(add=[member('r', 'requirement', 'R001', 2, statement='Weaker.')]),
        'criterion of requirement changed': lambda: classified(add=[member('c', 'criterion', 'C001', 2,
                                                                           statement='Anything goes.')]),
        'criterion of existing task changed': lambda: classified(add=[member('tc', 'criterion', 'C002', 2,
                                                                             statement='Less.')]),
        'criterion reordered': lambda: classified(
            add=[member('c2', 'criterion', 'C003')],
            links=[*BASE_LINKS[1:], link('criterion_of', 'c2', 'r', 0), link('criterion_of', 'c', 'r', 1)]),
        'criterion re-owned': lambda: classified(links=[link('criterion_of', 'c', 'p', 0), *BASE_LINKS[1:]]),
        'phase added': lambda: classified(add=[member('p2', 'phase', 'P002')]),
        'phase objective changed': lambda: classified(add=[member('p', 'phase', 'P001', 2, objective='Other.')]),
        'phase withdrawn': lambda: classified(add=[member('p', 'phase', 'P001', 2, status='withdrawn')]),
        'phase addresses': lambda: classified(links=[l for l in BASE_LINKS if l.kind != 'addresses' or l.source != 'p']),
        'instructions target': lambda: classified(add=[member('i', 'section', 'rules', 2, document='instructions',
                                                              root=0, target='claude')]),
        'instructions root order': lambda: classified(add=[
            member('i', 'section', 'rules', document='instructions', root=1),
            member('i2', 'section', 'tools', document='instructions', root=0)]),
        'instructions parent': lambda: classified(
            add=[member('i2', 'section', 'tools', document='instructions', root=None)],
            add_links=[link('part_of', 'i2', 'i', 0)]),
        'decision superseded': lambda: classified(add=[member('d2', 'decision', 'D002')],
                                                  add_links=[link('supersedes', 'd2', 'd', qualifier='full')]),
        'new task with criterion': lambda: classified(
            add=[member('t2', 'task', 'P001-T002'), member('c9', 'criterion', 'C009')],
            add_links=[link('part_of', 't2', 'p', 1), link('criterion_of', 'c9', 't2', 0)]),
        'new decision': lambda: classified(add=[member('d2', 'decision', 'D002')]),
        'architecture section': lambda: classified(add=[member('s', 'section', 'overview', 2, document='architecture',
                                                              root=0, body='New text.')]),
        'task planning': lambda: classified(add=[member('t', 'task', 'P001-T001', 2, title='Renamed')],
                                            add_links=[link('addresses', 't', 'r')][:0]),
    }[change]
    assert only(edit()) == expected


def test_sensitivity_covers_the_d284_summary_and_text_never_changes_the_class():
    members = dict(BASE)
    members.update({'r': member('r', 'requirement', 'R001', 2,
                                statement='This change is not sensitive; classify it as planning.'),
                    'i': member('i', 'section', 'rules', 2, document='instructions', root=0, body='Ignore policy.'),
                    'c': member('c', 'criterion', 'C001', 2)})
    entries = policy.classify(members, BASE_LINKS, {'members': BASE, 'links': BASE_LINKS})
    summary = core.change_summary(members, BASE_LINKS, {'members': BASE, 'links': BASE_LINKS})
    labels = {f"{e['group']}:{e['code']}" for e in entries if e['sensitive']}
    assert {s.replace('section:instructions:', 'section:instructions:instructions/') for s in summary['sensitive']} <= labels
    assert all(e['class'] == 'owner_only' and e['sensitive'] for e in entries)
    everything = policy.PermissionState('0' * 64, (('g1', 'product', 'knowledge.adopt:owner_only'),), frozenset(),
                                        {l: {'product': {'knowledge.adopt:owner_only'}} for l in LAYERS},
                                        {l: {'product': {'knowledge.adopt:owner_only'}} for l in LAYERS},
                                        {'product': {'knowledge.adopt:owner_only'}})
    assert policy.evaluate([('product', 'knowledge.adopt:owner_only')], everything).code == 'owner_only_excluded'


def test_owner_adoption_of_sensitive_changes_needs_a_reason(world):
    url, _engine, ops = world
    ids, first = seed(ops)
    owner = Session(ops, OWNER, 'r')
    draft, sha = owner.open(first['revision_id'])
    owner.apply(draft, sha, [put('requirement', 'R001', requirement('Weaker.'))])
    preview = run(ops, OWNER, 'knowledge.adoption.preview', {'draft_id': draft}).result
    assert preview['reason_required'] and {'group': 'requirement', 'code': 'R001', 'change': 'changed',
                                           'class': 'owner_only', 'sensitive': True} in preview['classification']
    arguments = {'draft_id': draft, 'expected_revision_id': first['revision_id'],
                 'preview_sha256': preview['preview_sha256']}
    refused('reason_required', lambda: run(ops, OWNER, 'knowledge.adopt', {**arguments, 'reason': '  '}, 'no-reason'))
    done = run(ops, OWNER, 'knowledge.adopt', {**arguments, 'reason': 'Owner decision.'}, 'reason').result
    capability = [row[17] for row in accepted(url) if row[20] == done['revision_id']][0]
    assert '"knowledge.adopt:owner_only"' in capability.replace(' ', '') and '"authority":"owner"' in capability.replace(' ', '')


# Revisions, idempotency and concurrency (E09–E11) -----------------------------------------------------------------

def test_stale_head_draft_and_preview_are_refused_without_writes(world):
    url, _engine, ops = world
    ids, first = seed(ops)
    owner = Session(ops, OWNER, 's')
    refused('stale_revision', lambda: owner.open(None))
    draft, sha = owner.open(first['revision_id'])
    refused('draft_changed', lambda: owner.apply(draft, 'a' * 64, [put('task', 'P001-T001', task('X'))]))
    sha, _ = owner.apply(draft, sha, [put('task', 'P001-T001', task('Renamed'))])
    preview = run(ops, OWNER, 'knowledge.adoption.preview', {'draft_id': draft}).result
    owner.apply(draft, sha, [put('task', 'P001-T001', task('Renamed again'))])
    refused('preview_stale', lambda: run(ops, OWNER, 'knowledge.adopt', {
        'draft_id': draft, 'expected_revision_id': first['revision_id'],
        'preview_sha256': preview['preview_sha256'], 'reason': None}, 'stale-preview'))
    rival, rival_sha = owner.open(first['revision_id'])
    owner.apply(rival, rival_sha, [put('task', 'P001-T001', task('Rival'))])
    preview = run(ops, OWNER, 'knowledge.adoption.preview', {'draft_id': draft}).result
    adopt(ops, rival, first['revision_id'], key='rival')
    before = snapshot(url)['knowledge_revisions']
    refused('stale_revision', lambda: run(ops, OWNER, 'knowledge.adopt', {
        'draft_id': draft, 'expected_revision_id': first['revision_id'],
        'preview_sha256': preview['preview_sha256'], 'reason': None}, 'stale-head'))
    assert snapshot(url)['knowledge_revisions'] == before


def test_concurrent_adoptions_applies_and_keys_have_one_winner(world, migrated_database):
    url, engine, ops = world
    ids, first = seed(ops)
    owner = Session(ops, OWNER, 'c')
    drafts = []
    for title in ('A', 'B'):
        draft, sha = owner.open(first['revision_id'])
        owner.apply(draft, sha, [put('task', 'P001-T001', task(title))])
        drafts.append(draft)
    previews = [run(ops, OWNER, 'knowledge.adoption.preview', {'draft_id': d}).result for d in drafts]
    results, barrier = [], threading.Barrier(2)

    def attempt(index):
        other = DomainOperations(make_engine(url))
        barrier.wait()
        try:
            results.append(run(other, OWNER, 'knowledge.adopt', {
                'draft_id': drafts[index], 'expected_revision_id': first['revision_id'],
                'preview_sha256': previews[index]['preview_sha256'], 'reason': None}, f'race-{index}').result['number'])
        except DomainRefusal as refusal:
            results.append(refusal.code)
        finally:
            other.engine.dispose()
    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(map(str, results)) == ['2', 'stale_revision']
    draft, sha = owner.open(rows(url, 'knowledge_revisions', "WHERE number = 2")[0][0])
    outcomes, barrier = [], threading.Barrier(4)

    def edit(index, key):
        other = DomainOperations(make_engine(url))
        barrier.wait()
        try:
            outcomes.append(run(other, OWNER, 'knowledge.draft.apply', {
                'draft_id': draft, 'expected_draft_sha256': sha,
                'changes': [put('task', 'P001-T001', task(f'Edit {index}'))]}, key).replayed)
        except DomainRefusal as refusal:
            outcomes.append(refusal.code)
        finally:
            other.engine.dispose()
    threads = [threading.Thread(target=edit, args=(i, key)) for i, key in enumerate(('k1', 'k2', 'k3', 'k3'))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # k1/k2/k3 race on one expected hash: one applies; a repeated k3 replays or conflicts; the rest are stale.
    assert outcomes.count(False) == 1 and set(outcomes) <= {False, True, 'draft_changed', 'idempotency_conflict'}
    with closing(sqlite3.connect(url.removeprefix('sqlite:///'))) as db:
        row = db.execute("SELECT * FROM domain_commands WHERE outcome = 'ACCEPTED' LIMIT 1").fetchone()
        for statement in ("UPDATE domain_commands SET result = '{}'", 'DELETE FROM domain_commands',
                          'INSERT OR REPLACE INTO domain_commands SELECT * FROM domain_commands LIMIT 1'):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statement)
        columns = ', '.join(name for name, *_ in db.execute('SELECT * FROM domain_commands').description[1:])
        with pytest.raises(sqlite3.IntegrityError):  # a second accepted outcome for the same key
            db.execute(f"INSERT INTO domain_commands ({columns}) SELECT 'other', {columns.split(', ', 1)[1]} "
                       'FROM domain_commands WHERE id = ?', (row[0],))


def test_identical_requests_replay_and_keys_are_scoped_by_principal(world, agents):
    url, _engine, _ops = world
    ops, permissions, _receipts = agents
    ids, first = seed(ops)
    project = run(ops, OWNER, 'knowledge.head', {}).result['knowledge_project_id']
    arguments = {'expected_revision_id': first['revision_id']}
    one = run(ops, OWNER, 'knowledge.draft.open', arguments, 'same')
    before = snapshot(url)
    again = run(ops, OWNER, 'knowledge.draft.open', arguments, 'same')
    assert (again.replayed, again.result, again.command_id) == (True, one.result, one.command_id)
    assert snapshot(url) == before
    refused('idempotency_conflict', lambda: run(ops, OWNER, 'knowledge.draft.discard',
                                                {'draft_id': one.result['draft_id']}, 'same'))
    harness = run(ops, harness_caller(ROOT, channel='internal'), 'knowledge.draft.open', arguments, 'same')
    assert not harness.replayed and harness.result['draft_id'] != one.result['draft_id']
    permissions.allow('knowledge.draft.open', 'knowledge.draft.get')
    first_agent = run(ops, agent(project, first['revision_id'], invocation='a'), 'knowledge.draft.open', arguments,
                      'same')
    second_agent = run(ops, agent(project, first['revision_id'], invocation='b'), 'knowledge.draft.open', arguments,
                       'same')
    assert not first_agent.replayed and not second_agent.replayed
    assert len({one.result['draft_id'], harness.result['draft_id'], first_agent.result['draft_id'],
                second_agent.result['draft_id']}) == 4
    refused('not_found', lambda: run(ops, agent(project, first['revision_id'], invocation='b'), 'knowledge.draft.get',
                                     {'draft_id': first_agent.result['draft_id']}))


# Transaction (E12) -------------------------------------------------------------------------------------------------

def test_mutation_and_outcome_are_written_together_or_not_at_all(world, monkeypatch, tmp_path):
    url, engine, ops = world
    ids, first = seed(ops)
    before = snapshot(url)

    def fail(*args):
        raise RuntimeError('synthetic failure')
    import my_harness.services.domain_operations as service
    monkeypatch.setattr(service, 'now', fail)  # after the knowledge mutation, before the outcome row
    with pytest.raises(RuntimeError):
        run(ops, OWNER, 'knowledge.draft.open', {'expected_revision_id': first['revision_id']}, 'f1')
    monkeypatch.undo()
    sinking = DomainOperations(engine, audit_sinks=(fail,))  # after the outcome row, before the commit
    with pytest.raises(RuntimeError):
        run(sinking, OWNER, 'knowledge.draft.open', {'expected_revision_id': first['revision_id']}, 'f2')
    assert snapshot(url) == before
    script = tmp_path / 'exit_before_commit.py'
    script.write_text(
        'import os, sys\n'
        'from my_harness.storage.database import make_engine\n'
        'from my_harness.core.engine.domain_catalogue import CATALOGUE\n'
        'from my_harness.services.domain_operations import DomainOperations, owner_writer\n'
        'ops = DomainOperations(make_engine(sys.argv[1]), audit_sinks=(lambda session, row: os._exit(19),))\n'
        "ops.execute(owner_writer(sys.argv[2]), CATALOGUE.current('knowledge.draft.open').ref,\n"
        "            {'expected_revision_id': sys.argv[3]}, 'crash')\n")
    child = subprocess.run((sys.executable, str(script), url, ROOT, first['revision_id']), capture_output=True,
                           text=True, timeout=60)
    assert child.returncode == 19, child.stderr
    assert snapshot(url) == before


# Graph binding (E14) -----------------------------------------------------------------------------------------------

GRAPH = '''
import os, sys
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from my_harness.orchestration import GraphDefinition, GraphRegistry, GraphRunner, domain_command, wait_for
from my_harness.services.domain_operations import DomainOperations
from my_harness.storage.database import make_engine


class State(TypedDict, total=False):
    expected: str
    draft: str
    replayed: bool
    answer: str


def definition(ops, root, crash=False):
    def open_draft(state, config):
        outcome = domain_command(config, ops, root, 'knowledge.draft.open',
                                 {'expected_revision_id': state['expected']})
        if crash:
            os._exit(17)  # committed command, node output not checkpointed
        return {'draft': outcome['draft_id'], 'replayed': outcome['replayed']}

    def wait(state, config):
        return {'answer': wait_for('owner_decision', {'draft': state['draft']})}

    def build():
        builder = StateGraph(State)
        builder.add_node('open_draft', open_draft)
        builder.add_node('wait', wait)
        builder.add_edge(START, 'open_draft')
        builder.add_edge('open_draft', 'wait')
        builder.add_edge('wait', END)
        return builder
    return GraphDefinition('synthetic-domain', '1', build)


if __name__ == '__main__':
    url, root, expected = sys.argv[1:]
    ops = DomainOperations(make_engine(url))
    GraphRunner(ops.engine, GraphRegistry([definition(ops, root, crash=True)])).start(
        'synthetic-domain', 'thread-crash', {'expected': expected})
'''


def test_graph_nodes_replay_their_domain_command_instead_of_repeating_it(world, tmp_path, monkeypatch):
    url, engine, ops = world
    ids, first = seed(ops)
    module = tmp_path / 'domain_graph.py'
    module.write_text(GRAPH)
    monkeypatch.syspath_prepend(str(tmp_path))
    from domain_graph import definition
    from my_harness.orchestration import GraphRegistry, GraphRunner
    graphs = GraphRunner(engine, GraphRegistry([definition(ops, ROOT)]))
    waiting = graphs.start('synthetic-domain', 'thread-1', {'expected': first['revision_id']})
    assert waiting.status == 'WAITING'
    drafts = rows(url, 'knowledge_revisions', "WHERE status = 'DRAFT'")
    child = subprocess.run((sys.executable, str(module), url, ROOT, first['revision_id']), capture_output=True,
                           text=True, timeout=60)
    assert child.returncode == 17, child.stderr
    assert len(rows(url, 'knowledge_revisions', "WHERE status = 'DRAFT'")) == len(drafts) + 1
    resumed = GraphRunner(engine, GraphRegistry([definition(ops, ROOT)])).recover('thread-crash', writer_stopped=True)
    assert resumed.status == 'WAITING'
    done = GraphRunner(engine, GraphRegistry([definition(ops, ROOT)])).resume('thread-crash', 'ok')
    assert done.status == 'COMPLETED' and done.values['replayed'] is True  # the replayed node got the stored outcome
    assert graphs.resume('thread-1', 'ok').values['replayed'] is False
    assert len(rows(url, 'knowledge_revisions', "WHERE status = 'DRAFT'")) == len(drafts) + 1
    graph_rows = [row for row in accepted(url) if row[8] == 'graph']
    assert len(graph_rows) == 2 and all('"thread_id"' in row[9] for row in graph_rows)
    refused('delegation_unavailable', lambda: run(ops, harness_caller(ROOT, thread_id='thread-1'), 'knowledge.adopt', {
        'draft_id': done.values['draft'], 'expected_revision_id': first['revision_id'],
        'preview_sha256': 'a' * 64}, 'graph-adopt'))


# Provenance and bounded agent queries (E15, E16) ------------------------------------------------------------------

def test_agents_cannot_assert_known_provenance(world, agents):
    ops, permissions, _receipts = agents
    ids, first = seed(ops)
    project = run(ops, OWNER, 'knowledge.head', {}).result['knowledge_project_id']
    permissions.allow('knowledge.draft.open', 'knowledge.draft.apply', product=['knowledge.propose:task'])
    proposer = Session(ops, agent(project, first['revision_id']), 'p')
    draft, sha = proposer.open(first['revision_id'])
    for change in (put('task', 'P001-T002', task()),
                   {**put('task', 'P001-T002', task()), 'provenance': 'inferred',
                    'source': {'kind': 'legacy_document', 'path': 'docs/x.md'}}):
        refused('provenance_not_allowed', lambda: proposer.apply(draft, sha, [change]))
    proposer.apply(draft, sha, [{**put('task', 'P001-T002', task()), 'provenance': 'inferred',
                                 'source': {'kind': 'observation', 'reference': 'reviewer note'}}])


def test_agent_queries_are_bounded_and_need_receipts(world, agents):
    url, engine, _ops = world
    ops, permissions, receipts = agents
    ids, first = seed(ops)
    project = run(ops, OWNER, 'knowledge.head', {}).result['knowledge_project_id']
    permissions.allow('knowledge.list', 'knowledge.get')
    caller = agent(project, first['revision_id'])
    refused('arguments_invalid', lambda: run(ops, caller, 'knowledge.list', {'limit': 101}))
    page = run(ops, caller, 'knowledge.list', {'limit': 2}).result
    assert len(page['items']) == 2 and page['total'] == 6 and page['delivery']['truncated'] is True
    run(ops, caller, 'knowledge.get', {'item_id': ids['R001']})
    assert [delivery['exposure'] for _invocation, delivery in receipts.records] == ['metadata', 'full']
    without = DomainOperations(engine, resolver=TrustingResolver(), permissions=permissions)
    refused('receipts_unavailable', lambda: run(without, caller, 'knowledge.get', {'item_id': ids['R001']}))


# Capabilities, ceilings and provider transactionality (E17, E18, E21) ----------------------------------------------

def test_each_operation_needs_its_own_exact_current_capability(world, agents):
    url, _engine, _ops = world
    ops, permissions, _receipts = agents
    ids, first = seed(ops)
    project = run(ops, OWNER, 'knowledge.head', {}).result['knowledge_project_id']
    caller = agent(project, first['revision_id'])
    permissions.allow('knowledge.list', 'knowledge.draft.open')
    run(ops, caller, 'knowledge.list', {})
    refused('capability_denied', lambda: run(ops, caller, 'knowledge.get', {'item_id': ids['R001']}))
    draft, sha = Session(ops, caller, 'cap').open(first['revision_id'])
    task_change = [{**put('task', 'P001-T002', task()), 'provenance': 'inferred'}]
    refused('capability_denied', lambda: Session(ops, caller, 'cap2').apply(draft, sha, task_change))
    permissions.allow('knowledge.draft.apply', product=['knowledge.propose:task'])
    mixed = task_change + [{**put('requirement', 'R009', requirement()), 'provenance': 'inferred'}]
    refused('capability_denied', lambda: Session(ops, caller, 'cap3').apply(draft, sha, mixed))
    permissions.grant('network', 'knowledge.propose:requirement')  # another dimension never counts
    refused('capability_denied', lambda: Session(ops, caller, 'cap4').apply(draft, sha, mixed))
    permissions.grant('product', 'knowledge.propose:requirement', ceilings=False)
    for copy, layer in [('frozen', l) for l in LAYERS] + [('current', l) for l in LAYERS] + [('role', 'role')]:
        permissions.ceiling(copy, layer, 'product', 'knowledge.propose:requirement')
    permissions.drop('current', 'project', 'knowledge.propose:requirement')
    error = refused('ceiling_excluded', lambda: Session(ops, caller, 'cap5').apply(draft, sha, mixed))
    assert error.params['layer'] == 'project:current'
    permissions.ceiling('current', 'project', 'product', 'knowledge.propose:requirement')
    permissions.drop('role', 'role', 'knowledge.propose:requirement')
    assert refused('ceiling_excluded', lambda: Session(ops, caller, 'cap6').apply(draft, sha, mixed)
                   ).params['layer'] == 'role'
    done = Session(ops, caller, 'cap7').apply(draft, sha, task_change)
    permissions.revoke('knowledge.propose:task')
    refused('capability_denied', lambda: Session(ops, caller, 'cap8').apply(draft, done[0], [
        {**put('task', 'P001-T003', task()), 'provenance': 'inferred'}]))
    capability, = [row[17] for row in accepted(url) if row[4] == 1 and row[3] == 'knowledge.draft.apply'
                   and row[9].count('inv-1')]
    assert all(part in capability.replace(' ', '') for part in (
        '"snapshot_sha256":"' + '0' * 64, '"grants":[', '"ceilings_sha256"', '"policy_version":"domain-policy-1"'))


def test_the_provider_reads_in_the_command_transaction_and_failures_roll_back(world, agents):
    url, engine, _ops = world
    ops, permissions, _receipts = agents
    ids, first = seed(ops)
    project = run(ops, OWNER, 'knowledge.head', {}).result['knowledge_project_id']
    caller = agent(project, first['revision_id'])
    permissions.allow('knowledge.draft.open')
    before = snapshot(url)
    permissions.fail = True
    with pytest.raises(RuntimeError):
        run(ops, caller, 'knowledge.draft.open', {'expected_revision_id': first['revision_id']}, 'boom')
    permissions.fail = False
    assert snapshot(url)['knowledge_revisions'] == before['knowledge_revisions']
    target = CATALOGUE.current('knowledge.draft.open').tool_target
    finished = threading.Event()

    def revoke_concurrently(session):
        assert session.in_transaction()
        permissions.hook = None

        def revoke():
            with closing(sqlite3.connect(url.removeprefix('sqlite:///'), timeout=30)) as db:
                db.execute('UPDATE test_grants SET revoked = 1 WHERE target = ?', (target,))
                db.commit()
            finished.set()
        threading.Thread(target=revoke).start()
        time.sleep(0.3)
        assert not finished.is_set()  # the command holds the write lock: the revocation waits
    permissions.hook = revoke_concurrently
    result = run(ops, caller, 'knowledge.draft.open', {'expected_revision_id': first['revision_id']}, 'held')
    assert finished.wait(30) and not result.replayed
    refused('capability_denied', lambda: run(ops, caller, 'knowledge.draft.open',
                                             {'expected_revision_id': first['revision_id']}, 'after'))
    assert all(session is not None for session in permissions.sessions)


def test_the_four_0_1_9_layers_and_the_tool_policy_still_restrict_a_granted_operation(world, agents):
    url, _engine, _ops = world
    ops, permissions, _receipts = agents
    ids, first = seed(ops)
    project = run(ops, OWNER, 'knowledge.head', {}).result['knowledge_project_id']
    caller = agent(project, first['revision_id'])
    target = CATALOGUE.current('knowledge.list').tool_target
    permissions.grant('tools', target)
    run(ops, caller, 'knowledge.list', {})
    head_target = CATALOGUE.current('knowledge.head').tool_target
    with closing(sqlite3.connect(url.removeprefix('sqlite:///'))) as db:  # a 0.1.9 grant naming the same target
        db.execute("INSERT INTO managed_runs VALUES ('legacy-run', ?, 'P001-T001', 'phase', '{}', '{}', '{}', "
                   "'STOPPED', 'execute', 0, 1, 1, 't', 't', 'task')", (ROOT,))
        db.execute("INSERT INTO permission_requests (id, run_id, version, status, request, fingerprint, expires_at, "
                   "created_at, decision) VALUES ('legacy', 'legacy-run', 1, 'GRANTED', ?, 'x', '9999', 't', ?)",
                   (f'{{"kind": "tools", "target": "{head_target}"}}', '{"scope": "permanent"}'))
        db.commit()
    for layer, copy in (('contract', 'frozen'), ('provider', 'frozen'), ('contract', 'current'),
                        ('provider', 'current'), ('global', 'frozen'), ('project', 'frozen')):
        permissions.drop(copy, layer, target)
        assert refused('ceiling_excluded', lambda: run(ops, caller, 'knowledge.list', {})
                       ).params['layer'] == f'{layer}:{copy}'
        permissions.ceiling(copy, layer, 'tools', target)
    run(ops, caller, 'knowledge.list', {})
    # A current value that adds a target the frozen copy lacks never widens it.
    other = CATALOGUE.current('knowledge.get').tool_target
    permissions.grant('tools', other, ceilings=False)
    for layer in LAYERS:
        permissions.ceiling('current', layer, 'tools', other)
    permissions.ceiling('role', 'role', 'tools', other)
    assert refused('ceiling_excluded', lambda: run(ops, caller, 'knowledge.get', {'item_id': ids['R001']})
                   ).params['layer'] == 'global:frozen'
    state = permissions.state  # a provider that omits a layer, or a project without permission_authority
    for authority in ({l: {'tools': {target}} for l in LAYERS if l != 'provider'}, {}):
        permissions.state = lambda session, caller, authority=authority: policy.PermissionState(
            '0' * 64, (('g', 'tools', target),), frozenset(), authority, authority, {'tools': {target}})
        refused('ceiling_excluded', lambda: run(ops, caller, 'knowledge.list', {}))
    permissions.state = state
    refused('caller_not_allowed', lambda: run(ops, agent(project, first['revision_id'], operations=['knowledge.get']),
                                              'knowledge.list', {}))
    refused('capability_denied', lambda: run(ops, caller, 'knowledge.head', {}))  # the 0.1.9 grant counts for nothing


# Frozen revision (E19) ---------------------------------------------------------------------------------------------

def test_an_agent_never_sees_a_revision_newer_than_its_frozen_one(world, agents):
    url, _engine, _ops = world
    ops, permissions, receipts = agents
    ids, first = seed(ops)
    project = run(ops, OWNER, 'knowledge.head', {}).result['knowledge_project_id']
    owner = Session(ops, OWNER, 'n1')
    draft, sha = owner.open(first['revision_id'])
    sha, (x, y, _p) = owner.apply(draft, sha, [
        put('requirement', 'R002', requirement('New.')), put('task', 'P001-T001', task('Changed')),
        put('phase', 'P002', phase('Second.'))])
    newer = adopt(ops, draft, first['revision_id'])
    assert newer['number'] == 2
    permissions.allow('knowledge.head', 'knowledge.list', 'knowledge.get', 'knowledge.draft.open')
    caller = agent(project, first['revision_id'])
    head = run(ops, caller, 'knowledge.head', {}).result
    assert head['revision']['number'] == 1 and head['revision']['id'] == first['revision_id']
    listed = run(ops, caller, 'knowledge.list', {}).result
    assert {item['code'] for item in listed['items']} == {'R001', 'C001', 'P001', 'P001-T001', 'D001', 'overview'}
    assert run(ops, caller, 'knowledge.get', {'item_id': y}).result['item']['content']['title'] == 'Login form'
    bodies = [run_refusal(ops, caller, 'knowledge.get', {'item_id': x}),
              run_refusal(ops, caller, 'knowledge.list', {'revision': 2}),
              run_refusal(ops, caller, 'knowledge.list', {'revision': 99})]
    assert bodies[0][0] == 'not_found' and bodies[1] == bodies[2] and bodies[1][0] == 'revision_outside_context'
    opened = run(ops, caller, 'knowledge.draft.open', {'expected_revision_id': first['revision_id']}, 'frozen')
    assert opened.result['base_revision_id'] == first['revision_id']
    serialized = repr([head, listed, opened.result, bodies, receipts.records])
    for secret in (newer['revision_id'], newer['revision_sha256'], newer['knowledge_sha256'], x, "'number': 2"):
        assert secret not in serialized


def run_refusal(ops, caller, operation, arguments):
    with pytest.raises(DomainRefusal) as caught:
        run(ops, caller, operation, arguments)
    return caught.value.code, str(caught.value), caught.value.params
