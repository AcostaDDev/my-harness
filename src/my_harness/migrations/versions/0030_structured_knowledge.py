"""P002-T004 / D284: structured knowledge, immutable versions and accepted revisions, protected by triggers.

No backfill: installed projects are converted by an explicit later path (T020). The triggers refuse every rewrite
of an accepted state in the database itself, including substitution by REPLACE or upsert.
"""
from alembic import op
import sqlalchemy as sa

revision = '0030_structured_knowledge'
down_revision = '0029_graph_continuations'
branch_labels = None
depends_on = None

TABLES = ('knowledge_identity_map', 'knowledge_revision_links', 'knowledge_revision_members',
          'knowledge_revisions', 'knowledge_item_versions', 'knowledge_items', 'knowledge_projects')
KINDS = ('requirement', 'criterion', 'phase', 'task', 'decision', 'section')
DOCUMENTS = ('specification', 'architecture', 'data_model', 'flows', 'instructions')
LINKS = ('part_of', 'criterion_of', 'depends_on', 'addresses', 'supersedes')
ORIGINS = ('owner_confirmed', 'owner_delegated', 'harness_deterministic')
LEGACY = ('managed_phase', 'phase_task', 'decision_heading', 'document_section')

_ABORT = "SELECT RAISE(ABORT, 'knowledge: accepted state is immutable')"
_DRAFT = "(SELECT status FROM knowledge_revisions WHERE id = {0}.revision_id) IS NOT 'DRAFT'"
TRIGGERS = {}
for _table, _key in (
        ('knowledge_projects', 'id = NEW.id OR root = NEW.root'),
        ('knowledge_items', "id = NEW.id OR project_id = NEW.project_id AND kind = NEW.kind AND code = NEW.code"
                            " AND document IS NEW.document"),
        ('knowledge_item_versions', 'id = NEW.id OR item_id = NEW.item_id AND number = NEW.number'),
        ('knowledge_identity_map', 'project_id = NEW.project_id AND legacy_kind = NEW.legacy_kind'
                                   ' AND legacy_ref = NEW.legacy_ref')):
    TRIGGERS[f'{_table}_no_update'] = f'CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table} BEGIN {_ABORT}; END'
    TRIGGERS[f'{_table}_no_delete'] = f'CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table} BEGIN {_ABORT}; END'
    TRIGGERS[f'{_table}_no_replace'] = (f'CREATE TRIGGER {_table}_no_replace BEFORE INSERT ON {_table} '
                                        f'WHEN EXISTS (SELECT 1 FROM {_table} WHERE {_key}) BEGIN {_ABORT}; END')
TRIGGERS['knowledge_revisions_insert'] = (
    "CREATE TRIGGER knowledge_revisions_insert BEFORE INSERT ON knowledge_revisions "
    "WHEN NEW.status IS NOT 'DRAFT' OR EXISTS (SELECT 1 FROM knowledge_revisions WHERE id = NEW.id) "
    "OR NEW.base_revision_id IS NOT NULL AND (SELECT status FROM knowledge_revisions "
    "WHERE id = NEW.base_revision_id) IS NOT 'ACCEPTED' "
    f"BEGIN {_ABORT}; END")
TRIGGERS['knowledge_revisions_update'] = (
    "CREATE TRIGGER knowledge_revisions_update BEFORE UPDATE ON knowledge_revisions "
    "WHEN OLD.status IS NOT 'DRAFT' OR NEW.status NOT IN ('ACCEPTED', 'DISCARDED') OR NEW.id IS NOT OLD.id "
    "OR NEW.project_id IS NOT OLD.project_id OR NEW.base_revision_id IS NOT OLD.base_revision_id "
    "OR NEW.created_at IS NOT OLD.created_at "
    "OR NEW.status = 'ACCEPTED' AND NEW.number IS NOT COALESCE((SELECT number FROM knowledge_revisions "
    "WHERE id = NEW.base_revision_id AND status = 'ACCEPTED'), 0) + 1 "
    f"BEGIN {_ABORT}; END")
TRIGGERS['knowledge_revisions_no_delete'] = (
    f'CREATE TRIGGER knowledge_revisions_no_delete BEFORE DELETE ON knowledge_revisions BEGIN {_ABORT}; END')
for _table in ('knowledge_revision_members', 'knowledge_revision_links'):
    TRIGGERS[f'{_table}_insert'] = (f"CREATE TRIGGER {_table}_insert BEFORE INSERT ON {_table} "
                                    f"WHEN {_DRAFT.format('NEW')} BEGIN {_ABORT}; END")
    TRIGGERS[f'{_table}_update'] = (f"CREATE TRIGGER {_table}_update BEFORE UPDATE ON {_table} "
                                    f"WHEN {_DRAFT.format('OLD')} OR {_DRAFT.format('NEW')} BEGIN {_ABORT}; END")
    TRIGGERS[f'{_table}_delete'] = (f"CREATE TRIGGER {_table}_delete BEFORE DELETE ON {_table} "
                                    f"WHEN {_DRAFT.format('OLD')} BEGIN {_ABORT}; END")


def upgrade():
    op.create_table('knowledge_projects',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('root', sa.String(), nullable=False, unique=True),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('knowledge_items',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('knowledge_projects.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('document', sa.String(20), nullable=True),
        sa.Column('code', sa.String(120), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.CheckConstraint(f'kind IN {KINDS}', name='ck_knowledge_item_kind'),
        sa.CheckConstraint(f"(kind = 'section') = (document IS NOT NULL) AND (document IS NULL OR document IN "
                           f"{DOCUMENTS})", name='ck_knowledge_item_document'),
        sa.UniqueConstraint('project_id', 'id', name='uq_knowledge_items_project'))
    op.create_index('uq_knowledge_items_code', 'knowledge_items', ['project_id', 'kind', 'code'], unique=True,
                    sqlite_where=sa.text('document IS NULL'))
    op.create_index('uq_knowledge_items_section', 'knowledge_items', ['project_id', 'document', 'code'], unique=True,
                    sqlite_where=sa.text("kind = 'section'"))
    op.create_table('knowledge_item_versions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('item_id', sa.String(36), sa.ForeignKey('knowledge_items.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('provenance', sa.String(10), nullable=False),
        sa.Column('source', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.CheckConstraint('number >= 1', name='ck_knowledge_version_number'),
        sa.CheckConstraint("provenance IN ('known', 'inferred', 'unknown')", name='ck_knowledge_version_provenance'),
        sa.UniqueConstraint('item_id', 'number', name='uq_knowledge_item_versions_number'),
        sa.UniqueConstraint('item_id', 'id', name='uq_knowledge_item_versions_item'))
    op.create_table('knowledge_revisions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('knowledge_projects.id'), nullable=False),
        sa.Column('base_revision_id', sa.String(36), nullable=True),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('number', sa.Integer(), nullable=True),
        sa.Column('knowledge_sha256', sa.String(64), nullable=True),
        sa.Column('revision_sha256', sa.String(64), nullable=True),
        sa.Column('origin', sa.String(30), nullable=True),
        sa.Column('actor', sa.JSON(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('changes', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('closed_at', sa.String(40), nullable=True),
        sa.CheckConstraint("status IN ('DRAFT', 'ACCEPTED', 'DISCARDED')", name='ck_knowledge_revision_status'),
        sa.CheckConstraint(
            "status = 'ACCEPTED' AND number >= 1 AND knowledge_sha256 IS NOT NULL AND revision_sha256 IS NOT NULL "
            f"AND origin IN {ORIGINS} AND actor IS NOT NULL AND changes IS NOT NULL AND closed_at IS NOT NULL "
            "OR status <> 'ACCEPTED' AND number IS NULL AND knowledge_sha256 IS NULL AND revision_sha256 IS NULL "
            "AND origin IS NULL AND actor IS NULL AND changes IS NULL AND reason IS NULL "
            "AND (status = 'DRAFT') = (closed_at IS NULL)", name='ck_knowledge_revision_adoption'),
        sa.UniqueConstraint('project_id', 'id', name='uq_knowledge_revisions_project'),
        sa.ForeignKeyConstraint(['project_id', 'base_revision_id'],
                                ['knowledge_revisions.project_id', 'knowledge_revisions.id'],
                                name='fk_knowledge_revisions_base'))
    op.create_index('uq_knowledge_revisions_number', 'knowledge_revisions', ['project_id', 'number'], unique=True,
                    sqlite_where=sa.text("status = 'ACCEPTED'"))
    op.create_index('uq_knowledge_revisions_base', 'knowledge_revisions', ['project_id', 'base_revision_id'],
                    unique=True, sqlite_where=sa.text("status = 'ACCEPTED' AND base_revision_id IS NOT NULL"))
    op.create_index('uq_knowledge_revisions_root', 'knowledge_revisions', ['project_id'], unique=True,
                    sqlite_where=sa.text("status = 'ACCEPTED' AND base_revision_id IS NULL"))
    op.create_table('knowledge_revision_members',
        sa.Column('revision_id', sa.String(36), primary_key=True),
        sa.Column('item_id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('version_id', sa.String(36), nullable=False),
        sa.Column('root_position', sa.Integer(), nullable=True),
        sa.CheckConstraint('root_position IS NULL OR root_position >= 0', name='ck_knowledge_member_root'),
        sa.ForeignKeyConstraint(['project_id', 'revision_id'],
                                ['knowledge_revisions.project_id', 'knowledge_revisions.id'],
                                name='fk_knowledge_members_revision'),
        sa.ForeignKeyConstraint(['project_id', 'item_id'], ['knowledge_items.project_id', 'knowledge_items.id'],
                                name='fk_knowledge_members_item'),
        sa.ForeignKeyConstraint(['item_id', 'version_id'],
                                ['knowledge_item_versions.item_id', 'knowledge_item_versions.id'],
                                name='fk_knowledge_members_version'))
    op.create_table('knowledge_revision_links',
        sa.Column('revision_id', sa.String(36), primary_key=True),
        sa.Column('kind', sa.String(20), primary_key=True),
        sa.Column('source_item_id', sa.String(36), primary_key=True),
        sa.Column('target_item_id', sa.String(36), primary_key=True),
        sa.Column('position', sa.Integer(), nullable=True),
        sa.Column('qualifier', sa.String(10), nullable=True),
        sa.CheckConstraint(f'kind IN {LINKS}', name='ck_knowledge_link_kind'),
        sa.CheckConstraint('source_item_id <> target_item_id', name='ck_knowledge_link_self'),
        sa.CheckConstraint("(kind IN ('part_of', 'criterion_of')) = (position IS NOT NULL) "
                           "AND (position IS NULL OR position >= 0)", name='ck_knowledge_link_position'),
        sa.CheckConstraint("(kind = 'supersedes') = (qualifier IS NOT NULL) "
                           "AND (qualifier IS NULL OR qualifier IN ('full', 'partial'))",
                           name='ck_knowledge_link_qualifier'),
        sa.ForeignKeyConstraint(['revision_id', 'source_item_id'],
                                ['knowledge_revision_members.revision_id', 'knowledge_revision_members.item_id'],
                                name='fk_knowledge_links_source'),
        sa.ForeignKeyConstraint(['revision_id', 'target_item_id'],
                                ['knowledge_revision_members.revision_id', 'knowledge_revision_members.item_id'],
                                name='fk_knowledge_links_target'))
    op.create_index('uq_knowledge_links_order', 'knowledge_revision_links',
                    ['revision_id', 'kind', 'target_item_id', 'position'], unique=True,
                    sqlite_where=sa.text('position IS NOT NULL'))
    op.create_table('knowledge_identity_map',
        sa.Column('project_id', sa.String(36), primary_key=True),
        sa.Column('legacy_kind', sa.String(30), primary_key=True),
        sa.Column('legacy_ref', sa.String(400), primary_key=True),
        sa.Column('item_id', sa.String(36), nullable=False),
        sa.Column('legacy_sha256', sa.String(64), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.CheckConstraint(f'legacy_kind IN {LEGACY}', name='ck_knowledge_identity_kind'),
        sa.ForeignKeyConstraint(['project_id', 'item_id'], ['knowledge_items.project_id', 'knowledge_items.id'],
                                name='fk_knowledge_identity_item'))
    for statement in TRIGGERS.values():
        op.execute(statement)


def downgrade():
    bind = op.get_bind()
    if any(bind.execute(sa.text(f'SELECT count(*) FROM {table}')).scalar() for table in TABLES):
        raise RuntimeError('Structured knowledge cannot be represented before 0030; keep this revision')
    for name in TRIGGERS:
        op.execute(f'DROP TRIGGER {name}')
    for table in TABLES:
        op.drop_table(table)
