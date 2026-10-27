"""Closing revision of H6.2: idempotency key when creating chat and planning conversations."""
from alembic import op
import sqlalchemy as sa

revision = '0018_conversation_keys'
down_revision = '0017_chat_context'
branch_labels = None
depends_on = None

TABLES = (('chat_conversations', 'uq_chat_conversations_key'),
          ('planning_conversations', 'uq_planning_conversations_key'))


def upgrade():
    # Nullable columns: earlier conversations have no key and SQLite does not recreate the tables.
    for table, index in TABLES:
        op.add_column(table, sa.Column('idempotency_key', sa.String(200), nullable=True))
        op.add_column(table, sa.Column('request_sha256', sa.String(64), nullable=True))
        op.create_index(index, table, ['idempotency_key'], unique=True)


def downgrade():
    # The key only deduplicates retries: losing it changes no conversation.
    for table, index in TABLES:
        op.drop_index(index, table_name=table)
        op.drop_column(table, 'request_sha256')
        op.drop_column(table, 'idempotency_key')
