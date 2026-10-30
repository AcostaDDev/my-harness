"""T009: immutable judge requests, invocation bindings, candidates and decision links. No backfill."""
from alembic import op
import sqlalchemy as sa

revision = '0034_judge_contracts'
down_revision = '0033_frozen_context'
branch_labels = None
depends_on = None
KEYS = {'judge_requests': ('id',), 'judge_invocations': ('request_id', 'attempt_id', 'invocation_id', 'operation_id'),
        'judge_rulings': ('id', 'request_id'), 'judge_decision_links': ('id',)}
TRIGGERS = {}
for table, keys in KEYS.items():
    abort = f"SELECT RAISE(ABORT, '{table}: records are immutable')"
    for action in ('update', 'delete'):
        name = f'{table}_no_{action}'
        TRIGGERS[name] = f'CREATE TRIGGER {name} BEFORE {action.upper()} ON {table} BEGIN {abort}; END'
    condition = ' OR '.join(f'{key} = NEW.{key}' for key in keys)
    if table == 'judge_requests':
        condition += ' OR (project_id = NEW.project_id AND equivalence_sha256 = NEW.equivalence_sha256 AND evidence_sha256 = NEW.evidence_sha256)'
    if table == 'judge_decision_links':
        condition += ' OR (ruling_id = NEW.ruling_id AND decision_id = NEW.decision_id AND revision_id = NEW.revision_id)'
    name = f'{table}_no_replace'
    TRIGGERS[name] = (f'CREATE TRIGGER {name} BEFORE INSERT ON {table} WHEN EXISTS '
                      f'(SELECT 1 FROM {table} WHERE {condition}) BEGIN {abort}; END')


def fk(name, target, *, primary=False, unique=False):
    return sa.Column(name, sa.String(80 if name == 'invocation_id' else 36), sa.ForeignKey(target),
                     primary_key=primary, nullable=False, unique=unique)


def upgrade():
    op.create_table('judge_requests', sa.Column('id', sa.String(36), primary_key=True),
        fk('project_id', 'knowledge_projects.id'), fk('snapshot_id', 'context_snapshots.id'),
        sa.Column('subject', sa.String(100), nullable=False), sa.Column('duty', sa.String(30), nullable=False),
        sa.Column('equivalence_sha256', sa.String(64), nullable=False),
        sa.Column('evidence_sha256', sa.String(64), nullable=False), sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('project_id', 'equivalence_sha256', 'evidence_sha256'))
    op.create_table('judge_invocations', fk('request_id', 'judge_requests.id', primary=True),
        fk('attempt_id', 'managed_attempts.id', unique=True), fk('invocation_id', 'usage_invocations.id', unique=True),
        fk('operation_id', 'workflow_operations.id', unique=True), sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('judge_rulings', sa.Column('id', sa.String(36), primary_key=True),
        fk('request_id', 'judge_requests.id', unique=True), sa.Column('status', sa.String(30), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False), sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('judge_decision_links', sa.Column('id', sa.String(36), primary_key=True),
        fk('ruling_id', 'judge_rulings.id'), fk('decision_id', 'knowledge_items.id'),
        fk('revision_id', 'knowledge_revisions.id'), sa.Column('created_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('ruling_id', 'decision_id', 'revision_id'))
    for sql in TRIGGERS.values():
        op.execute(sql)


def downgrade():
    for table in reversed(KEYS):
        if op.get_bind().execute(sa.text(f'SELECT count(*) FROM {table}')).scalar():
            raise RuntimeError('Judge evidence cannot be represented before 0034')
    for name in TRIGGERS:
        op.execute(f'DROP TRIGGER {name}')
    for table in reversed(KEYS):
        op.drop_table(table)
