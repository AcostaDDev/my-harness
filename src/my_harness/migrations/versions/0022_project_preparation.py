"""Django preparation journal and shared job/preparation ownership (D119)."""
from alembic import op
import sqlalchemy as sa

revision = '0022_project_preparation'
down_revision = '0021_project_creation'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('project_preparation_operations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('registered_projects.id'), nullable=False),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('idempotency_key', sa.String(200), nullable=False, unique=True),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('previous_id', sa.String(36), sa.ForeignKey('project_preparation_operations.id'), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('reserved', sa.Boolean(), nullable=False),
        sa.Column('plan', sa.JSON(), nullable=False),
        sa.Column('plan_sha256', sa.String(64), nullable=False),
        sa.Column('owner_token', sa.String(36), nullable=True),
        sa.Column('lease_until', sa.String(40), nullable=True),
        sa.Column('process_owner', sa.JSON(), nullable=True),
        sa.Column('owner_closed', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('cancel_requested', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('commit_intent', sa.JSON(), nullable=True),
        sa.Column('receipt', sa.JSON(), nullable=True),
        sa.Column('diagnostic', sa.Text(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_index('uq_preparation_reserved', 'project_preparation_operations', ['root'],
                    unique=True, sqlite_where=sa.text('reserved = 1'))
    op.create_table('project_preparation_steps',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('operation_id', sa.String(36), sa.ForeignKey('project_preparation_operations.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('spec', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.UniqueConstraint('operation_id', 'number'))
    op.create_table('project_preparation_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('operation_id', sa.String(36), sa.ForeignKey('project_preparation_operations.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('recorded_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('operation_id', 'version'))
    # Neither table has inbound FKs. Rebuild these leaves without disabling FK enforcement.
    op.create_table('_preparation_locks',
        sa.Column('root', sa.String(), primary_key=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('managed_jobs.id'), nullable=True, unique=True),
        sa.Column('preparation_id', sa.String(36), sa.ForeignKey('project_preparation_operations.id'),
                  nullable=True, unique=True),
        sa.CheckConstraint('(job_id IS NOT NULL) != (preparation_id IS NOT NULL)', name='ck_checkout_lock_owner'))
    op.execute('INSERT INTO _preparation_locks(root,job_id) SELECT root,job_id FROM checkout_locks')
    op.drop_table('checkout_locks')
    op.rename_table('_preparation_locks', 'checkout_locks')
    op.create_table('_preparation_processes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('attempt_id', sa.String(36), sa.ForeignKey('managed_attempts.id'), nullable=True, unique=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('managed_jobs.id'), nullable=True),
        sa.Column('preparation_id', sa.String(36), sa.ForeignKey('project_preparation_operations.id'), nullable=True),
        sa.Column('spec', sa.JSON(), nullable=False),
        sa.Column('identity', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('capture', sa.JSON(), nullable=True),
        sa.CheckConstraint('(job_id IS NOT NULL AND attempt_id IS NOT NULL AND preparation_id IS NULL) OR '
                           '(job_id IS NULL AND attempt_id IS NULL AND preparation_id IS NOT NULL)',
                           name='ck_managed_process_owner'))
    op.execute('INSERT INTO _preparation_processes(id,attempt_id,job_id,spec,identity,status,capture) '
               'SELECT attempt_id,attempt_id,job_id,spec,identity,status,capture FROM managed_processes')
    op.drop_table('managed_processes')
    op.rename_table('_preparation_processes', 'managed_processes')


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM project_preparation_operations')).scalar():
        raise RuntimeError('Preparation history cannot be represented before 0022; restore a backup in query mode')
    op.create_table('_job_locks',
        sa.Column('root', sa.String(), primary_key=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('managed_jobs.id'), nullable=False, unique=True))
    op.execute('INSERT INTO _job_locks(root,job_id) SELECT root,job_id FROM checkout_locks')
    op.drop_table('checkout_locks')
    op.rename_table('_job_locks', 'checkout_locks')
    op.create_table('_job_processes',
        sa.Column('attempt_id', sa.String(36), sa.ForeignKey('managed_attempts.id'), primary_key=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('managed_jobs.id'), nullable=False),
        sa.Column('spec', sa.JSON(), nullable=False),
        sa.Column('identity', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('capture', sa.JSON(), nullable=True))
    op.execute('INSERT INTO _job_processes(attempt_id,job_id,spec,identity,status,capture) '
               'SELECT attempt_id,job_id,spec,identity,status,capture FROM managed_processes')
    op.drop_table('managed_processes')
    op.rename_table('_job_processes', 'managed_processes')
    for table in ('project_preparation_events', 'project_preparation_steps', 'project_preparation_operations'):
        op.drop_table(table)
