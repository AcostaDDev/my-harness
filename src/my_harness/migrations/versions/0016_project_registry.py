"""H6.2 E2: project registry from the UI, versioned and audited, with logical retirement (D054/D076)."""
from alembic import op
import sqlalchemy as sa

revision = '0016_project_registry'
down_revision = '0015_planning'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('registered_projects',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('composition', sa.String(64), nullable=False),
        sa.Column('profile', sa.String(64), nullable=False),
        sa.Column('row', sa.JSON(), nullable=False),
        sa.Column('row_sha256', sa.String(64), nullable=False),
        sa.Column('trust', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_index('uq_registered_projects_active_root', 'registered_projects', ['root'], unique=True,
                    sqlite_where=sa.text("status = 'ACTIVE'"))
    op.create_table('registered_project_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('registered_projects.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('row', sa.JSON(), nullable=False),
        sa.Column('row_sha256', sa.String(64), nullable=False),
        sa.Column('previous_sha256', sa.String(64), nullable=True),
        sa.Column('preview_sha256', sa.String(64), nullable=False),
        sa.Column('actor', sa.JSON(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('recorded_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('project_id', 'version'),
        sqlite_autoincrement=True)


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT count(*) FROM registered_projects')).scalar():
        raise RuntimeError('Registered projects cannot be represented before 0016; keep this revision')
    op.drop_table('registered_project_events')
    op.drop_index('uq_registered_projects_active_root', table_name='registered_projects')
    op.drop_table('registered_projects')
