"""P002-T004 (D284, D285): structured knowledge, immutable accepted revisions and instruction staging.

Synthetic knowledge on temporary SQLite migrated to head; raw SQL runs through a connection configured like the
harness (`foreign_keys=ON`, `trusted_schema=OFF`). No model, CLI, Git, network or real project. Controls TM05
(criteria weakening and self-adoption become visible; earlier revisions cannot be altered).
"""
from contextlib import closing
import json
import sqlite3

from alembic import command
import pytest

from my_harness.core.engine import knowledge as core
from my_harness.core.engine.contracts import ContractError
from my_harness.storage.backup import BackupError, create_backup, restore_backup
from my_harness.storage.database import make_engine
from my_harness.storage.knowledge import KnowledgeIntegrityError, KnowledgeRepository, StaleRevision
from my_harness.storage.schema import SCHEMA_TRIGGERS_SHA256, require_schema, trigger_digest

KNOWLEDGE_TABLES = ('knowledge_identity_map', 'knowledge_revision_links', 'knowledge_revision_members',
                    'knowledge_revisions', 'knowledge_item_versions', 'knowledge_items', 'knowledge_projects')
OWNER = {'kind': 'owner', 'session': 'synthetic'}
AGENTS = """\
Intro line before any heading.

# Synthetic project — agent instructions

Canonical source for agents.

## Discovery

1. Read the state.

```sh
# not a heading inside a fence
scripts/check
```

## Rules

- Do not invent.

### Commands

Run the checks.
"""
CLAUDE = """\
# CLAUDE.md

@AGENTS.md

Notes for the client:

- Durable context lives in docs.
"""


def requirement(statement='Users can sign in.', status='active'):
    return {'title': 'Sign in', 'statement': statement, 'status': status}


def criterion(statement='A wrong password is refused.', status='active'):
    return {'statement': statement, 'status': status}


def phase(objective='Deliver sign in.'):
    return {'title': 'Accounts', 'objective': objective, 'tag': None, 'status': 'planned'}


def task(title='Login form'):
    return {'title': title, 'problem': 'No login.', 'expected_result': 'A login form.', 'subtasks': ['Form', 'Test'],
            'evidence': '', 'status': 'planned'}


def decision(title='Use sessions', status='accepted', historical=None):
    return {'title': title, 'context': '', 'decision': 'Server sessions.', 'alternatives': '', 'consequences': '',
            'status': status, 'historical_status': historical}


def section(title, body, target='agents'):
    return {'title': title, 'format': 'markdown', 'body': body, 'target': target, 'status': 'active'}


@pytest.fixture
def world(migrated_database):
    url = migrated_database[0]
    repo = KnowledgeRepository(make_engine(url))
    return url, repo, repo.project('/synthetic/project')


def raw(url):
    db = sqlite3.connect(url.removeprefix('sqlite:///'), isolation_level=None)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA trusted_schema=OFF')
    return closing(db)


def rows(url, table):
    with raw(url) as db:
        return db.execute(f'SELECT * FROM {table} ORDER BY 1, 2').fetchall()


def baseline(repo, project):
    """Revision 1: a requirement with a criterion, a phase with two ordered tasks, a decision and two root sections."""
    draft = repo.open_draft(project, None)
    r = repo.put(draft, 'requirement', 'R001', requirement())
    c = repo.put(draft, 'criterion', 'C001', criterion())
    p = repo.put(draft, 'phase', 'P001', phase())
    t1 = repo.put(draft, 'task', 'P001-T001', task())
    t2 = repo.put(draft, 'task', 'P001-T002', task('Logout'))
    repo.put(draft, 'decision', 'D001', decision())
    repo.put(draft, 'section', 'overview', section('Overview', 'What it is.\n'), document='specification',
             root_position=0)
    repo.put(draft, 'section', 'rules', section('Rules', 'Business rules.\n'), document='specification',
             root_position=1)
    repo.link(draft, 'criterion_of', c, r, position=0)
    repo.link(draft, 'part_of', t1, p, position=0)
    repo.link(draft, 'part_of', t2, p, position=1)
    repo.link(draft, 'depends_on', t2, t1)
    repo.link(draft, 'addresses', p, r)
    return repo.adopt(draft, None, origin='owner_confirmed', actor=OWNER, reason='initial')


# Adoption and retrieval ---------------------------------------------------------------------------------------------

def test_sequential_adoption_keeps_old_revisions_byte_identical(world):
    url, repo, project = world
    first = baseline(repo, project)
    assert (first.number, first.base_revision_id, first.origin) == (1, None, 'owner_confirmed')
    assert first.children('part_of', first.item('phase', 'P001').item_id) == [
        first.item('task', 'P001-T001').item_id, first.item('task', 'P001-T002').item_id]
    draft = repo.open_draft(project, first.id)
    repo.put(draft, 'phase', 'P001', phase('Deliver sign in and sign out.'))
    second = repo.adopt(draft, first.id, origin='owner_delegated', actor={'kind': 'harness', 'parent': 'auth-1'})
    assert second.number == 2 and second.base_revision_id == first.id
    assert second.changes['items'] == {'phase': {'added': [], 'changed': ['P001'], 'removed': []}}
    assert not second.changes['structure_changed'] and second.changes['sensitive'] == []
    again = repo.revision(project, 1)
    assert again == first
    assert repo.revision(project) == second
    assert second.item('phase', 'P001').version == 2 and again.item('phase', 'P001').version == 1
    assert [v.number for v in repo.history(second.item('phase', 'P001').item_id)] == [1, 2]
    assert second.revision_sha256 != first.revision_sha256


def test_stale_concurrent_discarded_and_empty_adoptions_are_refused(world):
    url, repo, project = world
    first = baseline(repo, project)
    a, b = repo.open_draft(project, first.id), repo.open_draft(project, first.id)
    repo.put(a, 'requirement', 'R002', requirement('Users can reset passwords.'))
    repo.put(b, 'requirement', 'R003', requirement('Users can delete accounts.'))
    with pytest.raises(StaleRevision):
        repo.adopt(a, None, origin='owner_confirmed', actor=OWNER)  # wrong expected revision
    repo.adopt(a, first.id, origin='owner_confirmed', actor=OWNER)
    with pytest.raises(StaleRevision):
        repo.adopt(b, first.id, origin='owner_confirmed', actor=OWNER)  # first wins; second is stale
    repo.discard(b)
    with pytest.raises(ValueError):
        repo.put(b, 'requirement', 'R004', requirement())
    with pytest.raises(ValueError):
        repo.adopt(b, repo.head(project).id, origin='owner_confirmed', actor=OWNER)
    empty = repo.open_draft(project, repo.head(project).id)
    with pytest.raises(ContractError):
        repo.adopt(empty, repo.head(project).id, origin='owner_confirmed', actor=OWNER)
    with pytest.raises(ContractError):
        repo.adopt(empty, repo.head(project).id, origin='model', actor=OWNER)
    assert repo.revision(project).number == 2


def test_relationship_constraints_are_checked_at_adoption(world):
    url, repo, project = world
    first = baseline(repo, project)
    ids = {m.code: m.item_id for m in first.members.values()}

    def refused(change):
        draft = repo.open_draft(project, first.id)
        change(draft)
        with pytest.raises(ContractError):
            repo.adopt(draft, first.id, origin='owner_confirmed', actor=OWNER)
        repo.discard(draft)
    refused(lambda d: repo.put(d, 'task', 'P001-T003', task('Orphan')))  # task without a phase
    refused(lambda d: repo.link(d, 'criterion_of', ids['C001'], ids['P001'], position=0))  # two owners
    refused(lambda d: repo.link(d, 'depends_on', ids['P001-T001'], ids['P001-T002']))  # cycle
    refused(lambda d: repo.link(d, 'addresses', ids['R001'], ids['P001']))  # wrong endpoints
    refused(lambda d: (repo.unlink(d, 'part_of', ids['P001-T001'], ids['P001']),
                       repo.link(d, 'part_of', ids['P001-T001'], ids['P001'], position=2)))  # not dense
    refused(lambda d: repo.put(d, 'section', 'rules', section('Rules', 'Business rules.\n'),
                               document='specification', root_position=0))  # duplicate root position
    refused(lambda d: repo.put(d, 'decision', 'D002', decision('Proposed', 'proposed')))  # proposed in accepted
    refused(lambda d: repo.put(d, 'decision', 'D001', decision('Rewritten')))  # accepted decision re-versioned
    refused(lambda d: repo.remove(d, ids['D001']))  # accepted decision removed
    with pytest.raises(ContractError):
        repo.put(repo.open_draft(project, first.id), 'section', 'notes', section('Notes', '', 'claude'),
                 document='specification')  # client target outside instructions
    with pytest.raises(ContractError):
        repo.put(repo.open_draft(project, first.id), 'task', 'T1', task())  # invalid code
    assert repo.revision(project) == first


def test_sections_belong_to_one_logical_document_with_identity_per_document(world):
    url, repo, project = world
    draft = repo.open_draft(project, None)
    spec = repo.put(draft, 'section', 'overview', section('Overview', 'Spec.\n'), document='specification',
                    root_position=0)
    arch = repo.put(draft, 'section', 'overview', section('Overview', 'Architecture.\n'), document='architecture',
                    root_position=0)
    child = repo.put(draft, 'section', 'modules', section('Modules', ''), document='architecture')
    repo.link(draft, 'part_of', child, spec, position=0)  # parent in another document
    with pytest.raises(ContractError):
        repo.adopt(draft, None, origin='owner_confirmed', actor=OWNER)
    repo.unlink(draft, 'part_of', child, spec)
    repo.link(draft, 'part_of', child, arch, position=0)
    revision = repo.adopt(draft, None, origin='owner_confirmed', actor=OWNER)
    assert spec != arch
    assert revision.item('section', 'overview', 'architecture').item_id == arch
    assert revision.roots('architecture') == [arch] and revision.children('part_of', arch) == [child]
    with pytest.raises(ContractError):
        core.validate_item('requirement', 'R001', 'specification')
    with pytest.raises(ContractError):
        core.validate_item('section', 'overview', 'readme')


# Root order and hashes ----------------------------------------------------------------------------------------------

def adopt_staged(repo, project, staged, base=None):
    draft = repo.open_draft(project, base)
    ids = {}
    for entry in staged['sections']:
        ids[entry['code']] = repo.put(
            draft, 'section', entry['code'], section(entry['title'], entry['body'], entry['target']),
            document='instructions', source={'kind': 'legacy_document', 'path': 'AGENTS.md'},
            root_position=entry['position'] if entry['parent'] is None else None)
    for entry in staged['sections']:
        if entry['parent'] is not None:
            repo.link(draft, 'part_of', ids[entry['code']], ids[entry['parent']], position=entry['position'])
    return repo.adopt(draft, base, origin='owner_confirmed', actor=OWNER, reason='import instructions')


def render(revision, target):
    """Test-only reconstruction (the renderer is T013): depth gives the heading level, bodies are verbatim."""
    out = []

    def walk(item_id, depth):
        member = revision.members[item_id]
        if member.content['title'] or depth:
            out.append('#' * depth + ' ' + member.content['title'] + '\n')
        out.append(member.content['body'])
        for child in revision.children('part_of', item_id):
            walk(child, depth + 1)
    for root in revision.roots('instructions'):
        if revision.members[root].content['target'] == target:
            walk(root, 0 if revision.members[root].code.endswith('preamble') else 1)
    return ''.join(out)


def test_staged_instructions_keep_preamble_and_section_order_verbatim(world):
    url, repo, project = world
    staged = core.stage_instructions(AGENTS, {'claude': CLAUDE})
    assert [s['code'] for s in staged['sections'] if s['parent'] is None] == [
        'preamble', 'synthetic-project-agent-instructions', 'claude-claude-md']
    assert {'kind': 'import_directive', 'target': 'claude'} in staged['report']
    revision = adopt_staged(repo, project, staged)
    assert render(revision, 'agents') == AGENTS
    assert render(revision, 'claude') == CLAUDE.replace('@AGENTS.md\n', '')
    roots = revision.roots('instructions')
    assert [revision.members[r].root_position for r in roots] == [0, 1, 2]
    assert revision.changes['sensitive'] == sorted(f'section:instructions:{s["code"]}' for s in staged['sections'])
    assert repo.revision(project) == revision


def test_swapping_two_roots_changes_the_knowledge_hash(world):
    url, repo, project = world
    first = adopt_staged(repo, project, core.stage_instructions(AGENTS))
    draft = repo.open_draft(project, first.id)
    preamble, title = first.roots('instructions')
    for item_id, position in ((preamble, 1), (title, 0)):
        member = first.members[item_id]
        repo.put(draft, 'section', member.code, member.content, document='instructions', source=member.source,
                 root_position=position)
    swapped = repo.adopt(draft, first.id, origin='owner_confirmed', actor=OWNER)
    assert swapped.roots('instructions') == [title, preamble]
    assert swapped.knowledge_sha256 != first.knowledge_sha256
    assert swapped.changes['structure_changed'] and swapped.changes['items'] == {}
    members = list(first.members.values())
    links = first.links
    reordered = [core.Member(**{**m.__dict__, 'root_position': 1 - m.root_position})
                 if m.root_position is not None else m for m in members]
    assert core.knowledge_sha256(project, reordered, links) != core.knowledge_sha256(project, members, links)
    child_order = [core.Link(l.kind, l.source, l.target, 1 - l.position, l.qualifier)
                   if l.target == title else l for l in links]
    assert core.knowledge_sha256(project, members, child_order) != core.knowledge_sha256(project, members, links)
    assert core.knowledge_sha256(project, reversed(members), reversed(links)) == first.knowledge_sha256


def test_heading_irregularities_are_reported_not_lost():
    staged = core.stage_instructions('# Title  \n\n### Deep\ntext\n')
    assert [r['kind'] for r in staged['report']] == ['heading_normalized', 'heading_level']
    assert ''.join(s['body'] for s in staged['sections']) == '\ntext\n'
    with pytest.raises(ContractError):
        core.stage_instructions('# A\n', {'agents': 'x'})


# TM05: visible criteria weakening ----------------------------------------------------------------------------------

def test_weakened_criterion_and_removed_requirement_are_listed_as_sensitive(world):
    url, repo, project = world
    first = baseline(repo, project)
    draft = repo.open_draft(project, first.id)
    repo.put(draft, 'criterion', 'C001', criterion('A wrong password may be accepted.'))
    repo.put(draft, 'task', 'P001-T001', task('Login form v2'))
    second = repo.adopt(draft, first.id, origin='owner_delegated', actor={'kind': 'harness', 'parent': 'auth-1'})
    assert second.changes['sensitive'] == ['criterion:C001']
    assert second.changes['items']['task']['changed'] == ['P001-T001']
    assert repo.revision(project, 1).item('criterion', 'C001').content['statement'] == 'A wrong password is refused.'


# Decisions ----------------------------------------------------------------------------------------------------------

def test_supersession_keeps_the_accepted_decision_and_derives_its_state(world):
    url, repo, project = world
    first = baseline(repo, project)
    old = first.item('decision', 'D001').item_id
    draft = repo.open_draft(project, first.id)
    new = repo.put(draft, 'decision', 'D002', decision('Use tokens'))
    repo.link(draft, 'supersedes', new, old, qualifier='full')
    second = repo.adopt(draft, first.id, origin='owner_confirmed', actor=OWNER)
    assert second.members[old] == first.members[old]
    draft = repo.open_draft(project, second.id)
    repo.unlink(draft, 'supersedes', new, old)
    with pytest.raises(ContractError):
        repo.adopt(draft, second.id, origin='owner_confirmed', actor=OWNER)
    repo.discard(draft)
    draft = repo.open_draft(project, second.id)
    third = repo.put(draft, 'decision', 'D003', decision('Use passkeys'))
    repo.link(draft, 'supersedes', third, old, qualifier='full')  # a second full superseder
    with pytest.raises(ContractError):
        repo.adopt(draft, second.id, origin='owner_confirmed', actor=OWNER)


def test_retired_decisions_exist_only_as_imported_first_versions(world):
    url, repo, project = world
    draft = repo.open_draft(project, None)
    with pytest.raises(ContractError):
        repo.put(draft, 'decision', 'D001', decision(status='retired'))
    legacy = {'kind': 'legacy_document', 'path': 'docs/DECISIONS.md', 'heading': 'D001', 'sha256': '0' * 64}
    repo.put(draft, 'decision', 'D001', decision(status='retired', historical='Status: superseded.'),
             source=legacy)
    revision = repo.adopt(draft, None, origin='owner_confirmed', actor=OWNER, reason='import')
    assert revision.item('decision', 'D001').content['historical_status'] == 'Status: superseded.'


@pytest.mark.parametrize('line, known, status, supersedes, report', [
    ('Status: accepted.', (), 'accepted', [], []),
    ('Status: accepted design in P002-T001; implementation pending T004.', (), 'accepted', [], []),
    ('Status: accepted; the closure part is superseded by D091.', ('D091',), 'accepted', [('D091', 'partial')], []),
    ('Status: accepted; supersedes the closure of D032.', ('D032',), 'accepted', [], []),
    ('Status: superseded by D268 (scope).', ('D268',), 'accepted', [('D268', 'full')], []),
    ('Status: partially superseded by D270.', ('D270',), 'accepted', [('D270', 'partial')], []),
    ('Status: superseded by D166–D168.', ('D166', 'D167', 'D168'), 'accepted',
     [('D166', None), ('D167', None), ('D168', None)], ['supersession_extent_required']),
    ('Status: superseded by D900.', (), 'retired', [], ['superseder_not_in_set', 'retired_without_superseder']),
    ('Estado: sustituida por D012.', ('D012',), 'accepted', [('D012', 'full')], []),
    ('Estado: rechazada.', (), 'rejected', [], []),
    ('Status: withdrawn.', (), 'rejected', [], []),
    ('Status: proposed, pending acceptance.', (), 'proposed', [], ['proposed_stays_draft']),
    ('Estado: propuesta.', (), 'proposed', [], ['proposed_stays_draft']),
    ('Status: under discussion.', (), None, [], ['unrecognized_status']),
    (None, (), None, [], ['unrecognized_status']),
])
def test_historical_decision_statuses_map_without_defaulting(line, known, status, supersedes, report):
    result = core.map_decision_status(line, known)
    assert (result['status'], result['supersedes'], result['report']) == (status, supersedes, report)
    assert result['historical_status'] == line


# Legacy identities --------------------------------------------------------------------------------------------------

def test_legacy_identities_map_once_without_touching_legacy_rows(world):
    url, repo, project = world
    with raw(url) as db:
        db.execute("INSERT INTO managed_phases (id, root, code, definition, definition_sha256, documents, status, "
                   "version, created_at, updated_at, definition_number) VALUES ('phase-1', '/synthetic/project', "
                   "'P001', ?, ?, '{}', 'OPEN', 1, 't', 't', 1)",
                   (json.dumps({'code': 'P001', 'tasks': ['P001-T001']}), '1' * 64))
    before = rows(url, 'managed_phases')
    first = baseline(repo, project)
    repo.map_legacy(project, 'managed_phase', 'phase-1', first.item('phase', 'P001').item_id)
    repo.map_legacy(project, 'phase_task', 'P001/P001-T001', first.item('task', 'P001-T001').item_id)
    assert repo.legacy(project, 'managed_phase', 'phase-1') == first.item('phase', 'P001').item_id
    assert repo.legacy(project, 'decision_heading', 'D001') is None  # never fabricated
    with pytest.raises(ValueError):
        repo.map_legacy(project, 'managed_phase', 'phase-1', first.item('task', 'P001-T001').item_id)
    with pytest.raises(ContractError):
        repo.map_legacy(project, 'run', 'x', first.item('phase', 'P001').item_id)
    assert rows(url, 'managed_phases') == before


# Database protections and substitution bypasses ---------------------------------------------------------------------

def test_substitution_bypasses_are_refused_by_the_database(world):
    url, repo, project = world
    first = baseline(repo, project)
    draft = repo.open_draft(project, first.id)
    repo.put(draft, 'requirement', 'R002', requirement('Second.'))
    spare = repo.put(repo.open_draft(project, first.id), 'requirement', 'R005', requirement('Spare.'))
    other = repo.project('/synthetic/other')
    other_draft = repo.open_draft(other, None)
    foreign = repo.put(other_draft, 'requirement', 'R001', requirement())
    before = {table: rows(url, table) for table in KNOWLEDGE_TABLES}
    with raw(url) as db:
        version = db.execute('SELECT id, item_id FROM knowledge_item_versions ORDER BY id LIMIT 1').fetchone()
        member = db.execute('SELECT item_id, version_id FROM knowledge_revision_members WHERE revision_id = ? '
                            'LIMIT 1', (first.id,)).fetchone()
        link = db.execute('SELECT kind, source_item_id, target_item_id FROM knowledge_revision_links '
                          'WHERE revision_id = ? LIMIT 1', (first.id,)).fetchone()
        # Neither the member's nor the spare item's own version, so the insertion below is always another item's.
        other_version = db.execute('SELECT v.id FROM knowledge_item_versions v WHERE v.item_id NOT IN (?, ?) LIMIT 1',
                                   (member[0], spare)).fetchone()[0]
        foreign_version = db.execute('SELECT id FROM knowledge_item_versions WHERE item_id = ?',
                                     (foreign,)).fetchone()[0]
        attempts = [
            ("UPDATE knowledge_item_versions SET content = '{}' WHERE id = ?", (version[0],)),
            ("UPDATE knowledge_item_versions SET item_id = ? WHERE id = ?", (member[0], version[0])),
            ('DELETE FROM knowledge_item_versions WHERE id = ?', (version[0],)),
            ("INSERT OR REPLACE INTO knowledge_item_versions (id, item_id, number, content, content_sha256, "
             "provenance, created_at) VALUES (?, ?, 1, '{}', 'x', 'known', 't')", version),
            ("INSERT INTO knowledge_item_versions (id, item_id, number, content, content_sha256, provenance, "
             "created_at) VALUES (?, ?, 1, '{}', 'x', 'known', 't') ON CONFLICT(id) DO UPDATE SET content = '{}'",
             version),
            ("UPDATE knowledge_items SET code = 'R999' WHERE id = ?", (member[0],)),
            ("INSERT OR REPLACE INTO knowledge_items (id, project_id, kind, code, created_at) "
             "SELECT id, project_id, kind, 'R998', created_at FROM knowledge_items WHERE id = ?", (member[0],)),
            ('DELETE FROM knowledge_items WHERE id = ?', (member[0],)),
            ("UPDATE knowledge_projects SET root = '/moved' WHERE id = ?", (project,)),
            ("INSERT OR REPLACE INTO knowledge_projects (id, root, created_at) VALUES (?, '/moved', 't')", (project,)),
            ('UPDATE knowledge_revision_members SET version_id = ? WHERE revision_id = ? AND item_id = ?',
             (other_version, first.id, member[0])),
            ('DELETE FROM knowledge_revision_members WHERE revision_id = ? AND item_id = ?', (first.id, member[0])),
            ('INSERT OR REPLACE INTO knowledge_revision_members (revision_id, item_id, project_id, version_id) '
             'VALUES (?, ?, ?, ?)', (first.id, member[0], project, member[1])),
            ('INSERT INTO knowledge_revision_members (revision_id, item_id, project_id, version_id) '
             'SELECT ?, item_id, project_id, version_id FROM knowledge_revision_members WHERE revision_id = ? '
             "AND item_id NOT IN (SELECT item_id FROM knowledge_revision_members WHERE revision_id = ?)",
             (first.id, draft, first.id)),
            ('UPDATE knowledge_revision_members SET revision_id = ? WHERE revision_id = ?', (first.id, draft)),
            ('UPDATE knowledge_revision_links SET position = 5 WHERE revision_id = ? AND kind = ?', (first.id, link[0])),
            ('DELETE FROM knowledge_revision_links WHERE revision_id = ?', (first.id,)),
            ('INSERT OR REPLACE INTO knowledge_revision_links (revision_id, kind, source_item_id, target_item_id, '
             'position, qualifier) SELECT revision_id, kind, source_item_id, target_item_id, position + 1, qualifier '
             'FROM knowledge_revision_links WHERE revision_id = ?', (first.id,)),
            ("UPDATE knowledge_revisions SET status = 'DRAFT', number = NULL, knowledge_sha256 = NULL, "
             "revision_sha256 = NULL, origin = NULL, actor = NULL, changes = NULL, reason = NULL, closed_at = NULL "
             "WHERE id = ?", (first.id,)),
            ("UPDATE knowledge_revisions SET reason = 'rewritten' WHERE id = ?", (first.id,)),
            ("UPDATE knowledge_revisions SET origin = 'owner_confirmed' WHERE id = ?", (first.id,)),
            ('DELETE FROM knowledge_revisions WHERE id = ?', (first.id,)),
            ("INSERT INTO knowledge_revisions (id, project_id, status, number, knowledge_sha256, revision_sha256, "
             "origin, actor, changes, created_at, closed_at) VALUES ('forged', ?, 'ACCEPTED', 2, 'x', 'y', "
             "'owner_confirmed', '{}', '{}', 't', 't')", (project,)),
            ("INSERT OR REPLACE INTO knowledge_revisions (id, project_id, status, created_at) "
             "VALUES (?, ?, 'DRAFT', 't')", (first.id, project)),
            ("UPDATE knowledge_revisions SET status = 'ACCEPTED', number = 3, knowledge_sha256 = 'x', "
             "revision_sha256 = 'y', origin = 'owner_confirmed', actor = '{}', changes = '{}', closed_at = 't' "
             "WHERE id = ?", (draft,)),  # skipped number
            ('INSERT INTO knowledge_revision_members (revision_id, item_id, project_id, version_id) '
             'VALUES (?, ?, ?, ?)', (draft, spare, project, other_version)),  # another item's version
            ('INSERT INTO knowledge_revision_members (revision_id, item_id, project_id, version_id) '
             'VALUES (?, ?, ?, ?)', (draft, foreign, project, foreign_version)),  # another project's item
            ("INSERT INTO knowledge_identity_map (project_id, legacy_kind, legacy_ref, item_id, created_at) "
             "VALUES (?, 'managed_phase', 'p', ?, 't')", (project, foreign)),  # cross-project mapping
        ]
        for statement, parameters in attempts:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statement, parameters)
        # A competing draft on the same base cannot be sealed as revision 2 once one exists.
        db.execute("UPDATE knowledge_revisions SET status = 'ACCEPTED', number = 2, knowledge_sha256 = 'x', "
                   "revision_sha256 = 'y', origin = 'owner_confirmed', actor = '{}', changes = '{}', "
                   "closed_at = 't' WHERE id = ?", (draft,))
        rival = repo.open_draft(project, first.id)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE knowledge_revisions SET status = 'ACCEPTED', number = 2, knowledge_sha256 = 'x', "
                       "revision_sha256 = 'y', origin = 'owner_confirmed', actor = '{}', changes = '{}', "
                       "closed_at = 't' WHERE id = ?", (rival,))
    after = {table: rows(url, table) for table in KNOWLEDGE_TABLES}
    assert after['knowledge_item_versions'] == before['knowledge_item_versions']
    assert after['knowledge_identity_map'] == before['knowledge_identity_map'] == []
    assert repo.revision(project, 1) == first
    # The raw seal above bypassed validation and hashing; retrieval refuses to serve it.
    with pytest.raises(KnowledgeIntegrityError):
        repo.revision(project)


def test_altered_rows_are_detected_on_read_when_triggers_are_removed(world):
    url, repo, project = world
    first = baseline(repo, project)
    second = repo.adopt(_add(repo, project, first), first.id, origin='owner_confirmed', actor=OWNER)
    with raw(url) as db:
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
            db.execute(f'DROP TRIGGER {name}')
        db.execute('UPDATE knowledge_revision_members SET root_position = 1 - root_position '
                   'WHERE revision_id = ? AND root_position IS NOT NULL', (first.id,))
    with pytest.raises(KnowledgeIntegrityError):
        repo.revision(project, 1)
    with pytest.raises(KnowledgeIntegrityError):
        repo.revision(project, second.number)  # the chain makes every later revision unservable
    with pytest.raises(RuntimeError):
        require_schema(make_engine(url))


def _add(repo, project, base):
    draft = repo.open_draft(project, base.id)
    repo.put(draft, 'requirement', 'R002', requirement('Second.'))
    return draft


def test_migration_installs_the_expected_triggers_and_refuses_a_downgrade_with_knowledge(world, migrated_database):
    url, repo, project = world
    with raw(url) as db:
        triggers = db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'").fetchall()
    assert len([name for name, _sql in triggers if name.startswith('knowledge_') and not name.startswith(('knowledge_deliveries_', 'knowledge_exchange_'))]) == 21
    assert trigger_digest(triggers) == SCHEMA_TRIGGERS_SHA256
    require_schema(make_engine(url))
    with pytest.raises(RuntimeError):
        command.downgrade(migrated_database[1], '0029_graph_continuations')
    assert rows(url, 'knowledge_projects')


def test_backup_keeps_protections_and_restored_copy_refuses_writes(world, tmp_path):
    url, repo, project = world
    first = baseline(repo, project)
    repo.engine.dispose()
    path = url.removeprefix('sqlite:///')
    create_backup(path, tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    restored = f"sqlite:///{tmp_path / 'restored/state.sqlite3'}"
    with raw(restored) as db:
        assert trigger_digest(db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")
                              .fetchall()) == SCHEMA_TRIGGERS_SHA256
    copy = KnowledgeRepository(make_engine(restored))
    assert copy.revision(project) == first
    for write in (lambda: copy.open_draft(project, first.id), lambda: copy.project('/synthetic/new'),
                  lambda: copy.map_legacy(project, 'managed_phase', 'p', first.item('phase', 'P001').item_id)):
        with pytest.raises(PermissionError):
            write()
    assert all(rows(restored, table) == rows(url, table) for table in KNOWLEDGE_TABLES)
    with raw(url) as db:
        db.execute('DROP TRIGGER knowledge_revisions_no_delete')
    with pytest.raises(BackupError):
        create_backup(path, tmp_path / 'backup-2', writers_stopped=True)
