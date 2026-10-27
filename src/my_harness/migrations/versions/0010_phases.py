"""H3.3: managed phases, questions, check/closure/reconciliation operations and authorizations."""
from alembic import op
import sqlalchemy as sa

revision = '0010_phases'
down_revision = '0009_permissions'
branch_labels = None
depends_on = None

OPEN = sa.text("status != 'CLOSED'")


def upgrade():
    with op.batch_alter_table('managed_runs') as batch:
        batch.add_column(sa.Column('purpose', sa.String(20), nullable=False, server_default='task'))
    op.create_table('managed_phases',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('code', sa.String(120), nullable=False),
        sa.Column('definition', sa.JSON(), nullable=False),
        sa.Column('definition_sha256', sa.String(64), nullable=False),
        sa.Column('documents', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('root', 'code'))
    op.create_index('uq_managed_phases_open_root', 'managed_phases', ['root'], unique=True, sqlite_where=OPEN)
    op.create_table('phase_questions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('managed_phases.id'), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('source', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('answer', sa.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('phase_operations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('managed_phases.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('managed_runs.id'), nullable=True),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('previous_status', sa.String(40), nullable=False),
        sa.Column('request', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('finished_at', sa.String(40), nullable=True))
    op.create_table('phase_authorizations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('managed_phases.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('scope', sa.JSON(), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('actor', sa.JSON(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.String(40), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('closed', sa.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False))
    op.create_table('phase_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('managed_phases.id'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('recorded_at', sa.String(40), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.UniqueConstraint('phase_id', 'sequence'),
        sqlite_autoincrement=True)


def downgrade():
    op.drop_table('phase_events')
    op.drop_table('phase_authorizations')
    op.drop_table('phase_operations')
    op.drop_table('phase_questions')
    op.drop_index('uq_managed_phases_open_root', table_name='managed_phases')
    op.drop_table('managed_phases')
    # Native DROP COLUMN (SQLite ≥ 3.35): recreating managed_runs would violate the foreign keys that reference it.
    op.execute('ALTER TABLE managed_runs DROP COLUMN purpose')
