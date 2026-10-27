"""P009-T002: UI authority and creation intents for new children (D116)."""
from alembic import op
import sqlalchemy as sa

revision = '0021_project_creation'
down_revision = '0020_project_imports'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('project_creation_root',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('path', sa.String(), nullable=True),
        sa.Column('identity', sa.JSON(), nullable=True),
        sa.Column('row_sha256', sa.String(64), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_creation_root_singleton'))
    op.create_table('project_creation_root_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False, unique=True),
        sa.Column('idempotency_key', sa.String(200), nullable=False, unique=True),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False))
    op.create_table('project_creation_operations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('idempotency_key', sa.String(200), nullable=False, unique=True),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('directory_name', sa.String(64), nullable=False),
        sa.Column('target', sa.String(), nullable=False),
        sa.Column('reserved', sa.Boolean(), nullable=False),
        sa.Column('authority', sa.JSON(), nullable=False),
        sa.Column('intent', sa.JSON(), nullable=False),
        sa.Column('intent_sha256', sa.String(64), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('child_identity', sa.JSON(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('diagnostic', sa.Text(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False))
    for column in ('project_id', 'target'):
        op.create_index('uq_creation_reserved_' + ('id' if column == 'project_id' else 'target'),
                        'project_creation_operations', [column], unique=True, sqlite_where=sa.text('reserved = 1'))
    op.create_table('project_creation_operation_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('operation_id', sa.String(36), sa.ForeignKey('project_creation_operations.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('idempotency_key', sa.String(200), nullable=True, unique=True),
        sa.Column('request_sha256', sa.String(64), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.UniqueConstraint('operation_id', 'version'))
    # Additive ALTER: do not rebuild/delete the parent table of the D078 events with foreign_keys=ON.
    op.execute('ALTER TABLE registered_projects ADD COLUMN creation_id VARCHAR(36) '
               'REFERENCES project_creation_operations(id)')
    op.create_index('uq_registered_creation', 'registered_projects', ['creation_id'], unique=True)


def downgrade():
    bind = op.get_bind()
    for table in ('project_creation_root', 'project_creation_root_events', 'project_creation_operations'):
        if bind.execute(sa.text('SELECT count(*) FROM ' + table)).scalar():
            raise RuntimeError('Creation authority/history cannot be represented before 0021; keep this revision')
    op.drop_index('uq_registered_creation', table_name='registered_projects')
    # Later SQLite table rebuilds turn the inline reference into a table foreign key.
    # Batch removal drops that reference together with its column on either representation.
    op.execute('PRAGMA defer_foreign_keys=ON')
    with op.batch_alter_table('registered_projects') as batch:
        batch.drop_column('creation_id')
    if bind.exec_driver_sql('PRAGMA foreign_key_check').first() is not None:
        raise RuntimeError('Creation downgrade found invalid foreign keys')
    op.execute('PRAGMA defer_foreign_keys=OFF')
    op.drop_table('project_creation_operation_events')
    op.drop_table('project_creation_operations')
    op.drop_table('project_creation_root_events')
    op.drop_table('project_creation_root')
