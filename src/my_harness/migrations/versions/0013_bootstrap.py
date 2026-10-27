"""H4.2: confirmed documentary bootstrap and its reconcilable initial intent."""
from alembic import op
import sqlalchemy as sa

revision = '0013_bootstrap'
down_revision = '0012_chat'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('project_bootstraps',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('root', sa.String(), nullable=False, unique=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('managed_runs.id'), nullable=False, unique=True),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('managed_phases.id'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('preview', sa.JSON(), nullable=False),
        sa.Column('intent', sa.JSON(), nullable=False),
        sa.Column('decision', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('finished_at', sa.String(40), nullable=True))


def downgrade():
    if (op.get_bind().execute(sa.text('SELECT count(*) FROM project_bootstraps')).scalar()
            or op.get_bind().execute(sa.text("SELECT count(*) FROM managed_runs WHERE purpose = 'bootstrap_discovery'")).scalar()):
        raise RuntimeError('Bootstrap history cannot be represented before 0013; keep this revision')
    op.drop_table('project_bootstraps')
