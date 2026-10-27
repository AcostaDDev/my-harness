"""E5: optional task as the default context of a conversation."""
from alembic import op
import sqlalchemy as sa

revision = '0017_chat_context'
down_revision = '0016_project_registry'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite supports adding a nullable reference without recreating a referenced table.
    op.execute('ALTER TABLE chat_conversations ADD COLUMN task_run_id VARCHAR(36) REFERENCES managed_runs(id)')


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM chat_conversations WHERE task_run_id IS NOT NULL')).scalar():
        raise RuntimeError('Task chat context cannot be represented before 0017')
    op.execute('ALTER TABLE chat_conversations DROP COLUMN task_run_id')
