"""H6.5: definition and phase planning conversations, frozen turns and proposals."""
from alembic import op
import sqlalchemy as sa

revision = '0015_planning'
down_revision = '0014_attempt_metrics'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('planning_conversations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('managed_phases.id'), nullable=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('brief', sa.JSON(), nullable=True),
        sa.Column('known', sa.JSON(), nullable=False),
        sa.Column('deferred', sa.JSON(), nullable=False),
        sa.Column('log', sa.JSON(), nullable=False),
        sa.Column('actor', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_index('uq_planning_definition', 'planning_conversations', ['root'], unique=True,
                    sqlite_where=sa.text("kind = 'definition'"))
    op.create_table('planning_turns',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('planning_conversations.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('managed_runs.id'), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('request', sa.JSON(), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('actor', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('finished_at', sa.String(40), nullable=True),
        sa.UniqueConstraint('conversation_id', 'number'))
    op.create_index('uq_planning_turns_pending', 'planning_turns', ['conversation_id'], unique=True,
                    sqlite_where=sa.text("status = 'QUEUED'"))
    op.create_table('planning_proposals',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('planning_conversations.id'), nullable=False),
        sa.Column('turn_id', sa.String(36), sa.ForeignKey('planning_turns.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('path', sa.String(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('base_sha256', sa.String(64), nullable=True),
        sa.Column('proposal_sha256', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('decision', sa.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('conversation_id', 'number'))


def downgrade():
    bind = op.get_bind()
    if (bind.execute(sa.text("SELECT count(*) FROM planning_conversations")).scalar()
            or bind.execute(sa.text("SELECT count(*) FROM managed_runs WHERE purpose IN "
                                    "('definition', 'phase_planning')")).scalar()):
        raise RuntimeError('Planning conversations cannot be represented before 0015; keep this revision')
    op.drop_table('planning_proposals')
    op.drop_index('uq_planning_turns_pending', table_name='planning_turns')
    op.drop_table('planning_turns')
    op.drop_index('uq_planning_definition', table_name='planning_conversations')
    op.drop_table('planning_conversations')
