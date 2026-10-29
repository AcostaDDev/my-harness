"""P002-T003 / D282: LangGraph continuation tables owned by the harness saver. Routing progress only, no backfill."""
from alembic import op
import sqlalchemy as sa

revision = '0029_graph_continuations'
down_revision = '0028_usage_accounting'
branch_labels = None
depends_on = None

TABLES = ('graph_checkpoint_writes', 'graph_checkpoints', 'graph_threads')
STATUSES = ('RUNNING', 'WAITING', 'COMPLETED', 'CANCELLED', 'REVOKED', 'QUARANTINED', 'RECOVERY_REQUIRED', 'FAILED')


def upgrade():
    op.create_table('graph_threads',
        sa.Column('id', sa.String(80), primary_key=True),
        sa.Column('graph_id', sa.String(120), nullable=False),
        sa.Column('graph_version', sa.String(40), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('segments', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(80), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.CheckConstraint(f"status IN {STATUSES}", name='ck_graph_thread_status'))
    op.create_index('ix_graph_threads_status', 'graph_threads', ['status'])
    op.create_table('graph_checkpoints',
        sa.Column('thread_id', sa.String(80), sa.ForeignKey('graph_threads.id'), primary_key=True),
        sa.Column('checkpoint_ns', sa.String(200), primary_key=True),
        sa.Column('checkpoint_id', sa.String(64), primary_key=True),
        sa.Column('parent_checkpoint_id', sa.String(64), nullable=True),
        sa.Column('checkpoint_type', sa.String(40), nullable=False),
        sa.Column('checkpoint', sa.LargeBinary(), nullable=False),
        sa.Column('metadata_type', sa.String(40), nullable=False),
        sa.Column('metadata_value', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('graph_checkpoint_writes',
        sa.Column('thread_id', sa.String(80), sa.ForeignKey('graph_threads.id'), primary_key=True),
        sa.Column('checkpoint_ns', sa.String(200), primary_key=True),
        sa.Column('checkpoint_id', sa.String(64), primary_key=True),
        sa.Column('task_id', sa.String(64), primary_key=True),
        sa.Column('idx', sa.Integer(), primary_key=True),
        sa.Column('channel', sa.String(200), nullable=False),
        sa.Column('value_type', sa.String(40), nullable=False),
        sa.Column('value', sa.LargeBinary(), nullable=False),
        sa.Column('task_path', sa.String(400), nullable=False))


def downgrade():
    bind = op.get_bind()
    if any(bind.execute(sa.text(f'SELECT count(*) FROM {table}')).scalar() for table in TABLES):
        raise RuntimeError('Graph continuations cannot be represented before 0029; keep this revision')
    op.drop_index('ix_graph_threads_status', 'graph_threads')
    for table in TABLES:
        op.drop_table(table)
