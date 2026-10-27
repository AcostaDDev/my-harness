"""H4.1: conversations, frozen turns and proposals of the contextual chat."""
from alembic import op
import sqlalchemy as sa

revision = '0012_chat'
down_revision = '0011_phase_amendments'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('chat_conversations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('managed_phases.id'), nullable=True),
        sa.Column('actor', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_table('chat_turns',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('chat_conversations.id'), nullable=False),
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
    op.create_index('uq_chat_turns_pending', 'chat_turns', ['conversation_id'], unique=True,
                    sqlite_where=sa.text("status = 'QUEUED'"))
    op.create_table('chat_proposals',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('chat_conversations.id'), nullable=False),
        sa.Column('turn_id', sa.String(36), sa.ForeignKey('chat_turns.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('proposal', sa.JSON(), nullable=False),
        sa.Column('proposal_sha256', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('managed_runs.id'), nullable=True, unique=True),
        sa.Column('decision', sa.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('conversation_id', 'number'))


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM managed_runs WHERE purpose = 'chat'")).scalar():
        raise RuntimeError('Chat turns cannot be represented before 0012; keep this revision')
    op.drop_table('chat_proposals')
    op.drop_index('uq_chat_turns_pending', table_name='chat_turns')
    op.drop_table('chat_turns')
    op.drop_table('chat_conversations')
