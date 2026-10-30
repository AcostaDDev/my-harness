"""T010 persisted permission lifecycle and frozen boundaries; no legacy backfill."""
from alembic import op
import sqlalchemy as sa

revision = '0035_permissions'
down_revision = '0034_judge_contracts'
branch_labels = depends_on = None
KEYS = {'permission_records': ('id',), 'permission_boundaries': ('invocation_id', 'snapshot_id', 'attempt_id')}
TRIGGERS = {}
for table, keys in KEYS.items():
    abort = f"SELECT RAISE(ABORT, '{table}: records are immutable')"
    for action in ('update', 'delete'):
        name = f'{table}_no_{action}'
        TRIGGERS[name] = f'CREATE TRIGGER {name} BEFORE {action.upper()} ON {table} BEGIN {abort}; END'
    condition = ' OR '.join(f'{key} = NEW.{key}' for key in keys)
    if table == 'permission_records':
        condition += ' OR (project_id = NEW.project_id AND (sequence = NEW.sequence OR record_key = NEW.record_key))'
    name = f'{table}_no_replace'
    TRIGGERS[name] = f'CREATE TRIGGER {name} BEFORE INSERT ON {table} WHEN EXISTS (SELECT 1 FROM {table} WHERE {condition}) BEGIN {abort}; END'


def upgrade():
    op.create_table('permission_records', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('knowledge_projects.id'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False), sa.Column('record_key', sa.String(240), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False), sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False), sa.Column('created_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('project_id', 'sequence'), sa.UniqueConstraint('project_id', 'record_key'))
    op.create_table('permission_boundaries',
        sa.Column('invocation_id', sa.String(80), sa.ForeignKey('usage_invocations.id'), primary_key=True),
        sa.Column('snapshot_id', sa.String(36), sa.ForeignKey('permission_records.id'), nullable=False, unique=True),
        sa.Column('attempt_id', sa.String(36), sa.ForeignKey('managed_attempts.id'), nullable=False, unique=True),
        sa.Column('operation_id', sa.String(36), sa.ForeignKey('workflow_operations.id'), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))
    for sql in TRIGGERS.values():
        op.execute(sql)


def downgrade():
    for table in KEYS:
        if op.get_bind().execute(sa.text(f'SELECT count(*) FROM {table}')).scalar():
            raise RuntimeError('Permission evidence cannot be represented before 0035')
    for name in TRIGGERS:
        op.execute(f'DROP TRIGGER {name}')
    for table in reversed(KEYS):
        op.drop_table(table)
