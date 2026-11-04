"""P002-T016 autonomous roadmap runs: sealed authorizations, run state, delegated children, persistent bound
consumption, durable owner questions, deduplicable events and sealed readiness gap reports and owner answers. No backfill; empty on upgrade."""
from alembic import op
import sqlalchemy as sa

revision = '0038_autonomous_runs'
down_revision = '0037_task_lineage'
branch_labels = depends_on = None
INSERT_ONLY = ('autonomous_authorizations', 'autonomous_children', 'autonomous_consumption', 'autonomous_events',
               'autonomous_reviews')
TABLES = ('autonomous_reviews', 'autonomous_events', 'autonomous_questions', 'autonomous_consumption', 'autonomous_children',
          'autonomous_runs', 'autonomous_authorizations')
STATES = "('RUNNING', 'WAITING_FOR_OWNER', 'PAUSED', 'LIMIT_REACHED', 'FAILED', 'RECOVERY_REQUIRED', 'REVOKED', 'COMPLETED')"
BOUNDS = "('task_attempts', 'judge_reconsiderations', 'replacement_plans', 'remediation_per_cause', 'no_progress')"


def upgrade():
    op.create_table('autonomous_authorizations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('knowledge_projects.id'), nullable=False),
        sa.Column('lineage_id', sa.String(36), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('previous_id', sa.String(36), sa.ForeignKey('autonomous_authorizations.id'), nullable=True),
        sa.Column('idempotency_key', sa.String(200), nullable=False, unique=True),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('preview', sa.JSON(), nullable=False),
        sa.Column('preview_sha256', sa.String(64), nullable=False),
        sa.Column('origin', sa.String(30), nullable=False),
        sa.Column('policy', sa.JSON(), nullable=False),
        sa.Column('permission_record_id', sa.String(36), sa.ForeignKey('permission_records.id'), nullable=False,
                  unique=True),
        sa.Column('actor', sa.JSON(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('lineage_id', 'number'),
        sa.CheckConstraint("origin = 'owner_confirmed'", name='ck_autonomous_authorization_origin'),
        sa.CheckConstraint('number >= 1', name='ck_autonomous_authorization_number'))
    op.create_table('autonomous_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('lineage_id', sa.String(36), nullable=False, unique=True),
        sa.Column('authorization_id', sa.String(36), sa.ForeignKey('autonomous_authorizations.id'), nullable=False),
        sa.Column('thread_id', sa.String(80), nullable=False, unique=True),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('reason', sa.String(80), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.CheckConstraint(f'status IN {STATES}', name='ck_autonomous_run_status'))
    op.create_index('ux_autonomous_runs_active_root', 'autonomous_runs', ['root'], unique=True,
                    sqlite_where=sa.text("status NOT IN ('REVOKED', 'COMPLETED')"))
    op.create_table('autonomous_children',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('autonomous_runs.id'), nullable=False),
        sa.Column('authorization_id', sa.String(36), sa.ForeignKey('autonomous_authorizations.id'), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('operation_key', sa.String(80), nullable=False, unique=True),
        sa.Column('subject', sa.JSON(), nullable=False),
        sa.Column('preview_sha256', sa.String(64), nullable=False),
        sa.Column('rule', sa.String(80), nullable=False),
        sa.Column('ruling_id', sa.String(36), sa.ForeignKey('judge_rulings.id'), nullable=True),
        sa.Column('permission_record_id', sa.String(36), sa.ForeignKey('permission_records.id'), nullable=True),
        sa.Column('origin', sa.String(30), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.CheckConstraint("origin = 'owner_delegated'", name='ck_autonomous_child_origin'))
    op.create_table('autonomous_consumption',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('bound', sa.String(40), nullable=False),
        sa.Column('identity', sa.String(240), nullable=False),
        sa.Column('consumption_key', sa.String(240), nullable=False, unique=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('autonomous_runs.id'), nullable=False),
        sa.Column('authorization_id', sa.String(36), sa.ForeignKey('autonomous_authorizations.id'), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.CheckConstraint(f'bound IN {BOUNDS}', name='ck_autonomous_consumption_bound'))
    op.create_index('ix_autonomous_consumption_identity', 'autonomous_consumption', ['root', 'bound', 'identity'])
    op.create_table('autonomous_questions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('autonomous_runs.id'), nullable=False),
        sa.Column('dedupe_key', sa.String(240), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('subject', sa.JSON(), nullable=False),
        sa.Column('binding', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('answer', sa.JSON(), nullable=True),
        sa.Column('answer_key', sa.String(200), nullable=True, unique=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('run_id', 'dedupe_key'),
        sa.CheckConstraint("status IN ('OPEN', 'ANSWERED', 'SUPERSEDED')", name='ck_autonomous_question_status'))
    op.create_table('autonomous_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('autonomous_runs.id'), nullable=False),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('kind', sa.String(60), nullable=False),
        sa.Column('dedupe_key', sa.String(240), nullable=False, unique=True),
        sa.Column('refs', sa.JSON(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('autonomous_reviews',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('knowledge_projects.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('record_key', sa.String(240), nullable=False, unique=True),
        sa.Column('revision_id', sa.String(80), nullable=False),
        sa.Column('revision_sha256', sa.String(64), nullable=False),
        sa.Column('gap_sha256', sa.String(64), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('origin', sa.String(30), nullable=False),
        sa.Column('actor', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.CheckConstraint("kind IN ('report', 'answer', 'task_plan')", name='ck_autonomous_review_kind'),
        sa.CheckConstraint("origin IN ('owner_confirmed', 'harness_deterministic')", name='ck_autonomous_review_origin'))
    op.create_index('ix_autonomous_reviews_revision', 'autonomous_reviews', ['root', 'revision_id', 'kind'])
    for table in INSERT_ONLY:
        for action in ('UPDATE', 'DELETE'):
            op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
                       f"BEGIN SELECT RAISE(ABORT, '{table}: records are immutable'); END")


def downgrade():
    connection = op.get_bind()
    for table in TABLES:
        if connection.execute(sa.text(f'SELECT count(*) FROM {table}')).scalar():
            raise RuntimeError('Autonomous run evidence cannot be represented before 0038')
    for table in INSERT_ONLY:
        for action in ('update', 'delete'):
            op.execute(f'DROP TRIGGER IF EXISTS {table}_no_{action}')
    op.drop_index('ix_autonomous_reviews_revision', table_name='autonomous_reviews')
    op.drop_index('ix_autonomous_consumption_identity', table_name='autonomous_consumption')
    op.drop_index('ux_autonomous_runs_active_root', table_name='autonomous_runs')
    for table in TABLES:
        op.drop_table(table)
