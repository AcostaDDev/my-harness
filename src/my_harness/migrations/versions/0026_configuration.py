"""P013-T004 / D221: additive versioned configuration references and recoverable intents."""
from alembic import op
import sqlalchemy as sa

revision = '0026_configuration'
down_revision = '0025_project_work_languages'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('configuration_scopes',
        sa.Column('scope', sa.String(80), primary_key=True),
        sa.Column('directory', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('saved_revision', sa.Integer(), nullable=True),
        sa.Column('active_revision', sa.Integer(), nullable=True),
        sa.Column('pending_revision', sa.Integer(), nullable=True),
        sa.Column('pending_operation_id', sa.String(36), nullable=True),
        sa.Column('working_sha256', sa.String(64), nullable=True),
        sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_table('configuration_operations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('format', sa.String(40), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('idempotency_key', sa.String(200), nullable=False, unique=True),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.CheckConstraint("status IN ('INTENDED', 'FILES_WRITTEN', 'SAVED', 'RECOVERY_REQUIRED', 'CONFLICT', 'APPLIED')",
                           name='ck_configuration_operation_status'))
    op.create_table('configuration_revisions',
        sa.Column('scope', sa.String(80), sa.ForeignKey('configuration_scopes.scope'), primary_key=True),
        sa.Column('revision', sa.Integer(), primary_key=True),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('operation_id', sa.String(36), sa.ForeignKey('configuration_operations.id'), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT', 'VALIDATED')", name='ck_configuration_revision_status'))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM configuration_operations')).scalar():
        raise RuntimeError('Configuration history cannot be represented before 0026; keep this revision')
    op.drop_table('configuration_revisions')
    op.drop_table('configuration_operations')
    op.drop_table('configuration_scopes')
