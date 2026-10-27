"""P008-T012: confirmed and reconcilable documentary imports."""
from alembic import op
import sqlalchemy as sa

revision = '0020_project_imports'
down_revision = '0019_import_conversations'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('project_imports',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('root', sa.String(), nullable=False, unique=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('planning_conversations.id'), nullable=False, unique=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('managed_runs.id'), nullable=False, unique=True),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('managed_phases.id'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('preview', sa.JSON(), nullable=False),
        sa.Column('intent', sa.Text(), nullable=False),
        sa.Column('decision', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('finished_at', sa.String(40), nullable=True))


def downgrade():
    if (op.get_bind().execute(sa.text('SELECT count(*) FROM project_imports')).scalar()
            or op.get_bind().execute(sa.text("SELECT count(*) FROM managed_runs WHERE purpose = 'import_commit'")).scalar()):
        raise RuntimeError('Import history cannot be represented before 0020; keep this revision')
    op.drop_table('project_imports')
