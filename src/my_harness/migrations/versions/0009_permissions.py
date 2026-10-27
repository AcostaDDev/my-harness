"""Permission requests, decisions and next-attempt consumption."""
from alembic import op
import sqlalchemy as sa

revision = '0009_permissions'
down_revision = '0008_prompt_versions'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('permission_requests',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(), sa.ForeignKey('managed_runs.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('request', sa.JSON(), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.String(40), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('decision', sa.JSON(), nullable=True),
        sa.Column('consumed_by', sa.String(36), nullable=True),
        sa.Column('supersedes', sa.String(36), sa.ForeignKey('permission_requests.id'), nullable=True))


def downgrade():
    op.drop_table('permission_requests')
