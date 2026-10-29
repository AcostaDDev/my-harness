"""P002-T007: immutable preparation, invocation boundary and exact delivery evidence. No backfill."""
from alembic import op
import sqlalchemy as sa

revision = '0033_frozen_context'
down_revision = '0032_operation_journal'
branch_labels = None
depends_on = None

KEYS = {'context_snapshots': ('id',), 'invocation_contexts': ('invocation_id', 'attempt_id', 'operation_id'),
        'knowledge_deliveries': ('id',)}
TRIGGERS = {}
for table, keys in KEYS.items():
    abort = f"SELECT RAISE(ABORT, '{table}: records are immutable')"
    for action in ('update', 'delete'):
        name = f'{table}_no_{action}'
        TRIGGERS[name] = f'CREATE TRIGGER {name} BEFORE {action.upper()} ON {table} BEGIN {abort}; END'
    name = f'{table}_no_replace'
    condition = ' OR '.join(f'{key} = NEW.{key}' for key in keys)
    if table == 'knowledge_deliveries':
        condition += ' OR (invocation_id = NEW.invocation_id AND key = NEW.key)'
    TRIGGERS[name] = (f'CREATE TRIGGER {name} BEFORE INSERT ON {table} WHEN EXISTS '
                      f'(SELECT 1 FROM {table} WHERE {condition}) BEGIN {abort}; END')


def upgrade():
    op.create_table('context_snapshots',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('knowledge_projects.id'), nullable=False),
        sa.Column('revision_id', sa.String(36), sa.ForeignKey('knowledge_revisions.id'), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('invocation_contexts',
        sa.Column('invocation_id', sa.String(80), sa.ForeignKey('usage_invocations.id'), primary_key=True),
        sa.Column('attempt_id', sa.String(36), sa.ForeignKey('managed_attempts.id'), nullable=False, unique=True),
        sa.Column('operation_id', sa.String(36), sa.ForeignKey('workflow_operations.id'), nullable=False, unique=True),
        sa.Column('snapshot_id', sa.String(36), sa.ForeignKey('context_snapshots.id'), nullable=False),
        sa.Column('prompt_sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('knowledge_deliveries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('invocation_id', sa.String(80), sa.ForeignKey('invocation_contexts.invocation_id'), nullable=False),
        sa.Column('key', sa.String(200), nullable=False), sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('channel', sa.String(30), nullable=False), sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False), sa.Column('receipts', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False), sa.UniqueConstraint('invocation_id', 'key'))
    for statement in TRIGGERS.values():
        op.execute(statement)


def downgrade():
    for table in reversed(KEYS):
        if op.get_bind().execute(sa.text(f'SELECT count(*) FROM {table}')).scalar():
            raise RuntimeError('Frozen context evidence cannot be represented before 0033')
    for name in TRIGGERS:
        op.execute(f'DROP TRIGGER {name}')
    for table in reversed(KEYS):
        op.drop_table(table)
