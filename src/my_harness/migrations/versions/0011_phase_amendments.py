"""H3.4: preserved phase definition versions and explicit abandonment (terminal state)."""
from datetime import datetime, timezone
import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = '0011_phase_amendments'
down_revision = '0010_phases'
branch_labels = None
depends_on = None

OPEN_BEFORE = sa.text("status != 'CLOSED'")
OPEN_AFTER = sa.text("status NOT IN ('CLOSED', 'ABANDONED')")


def upgrade():
    # Native ADD COLUMN: recreating managed_phases would break the foreign keys that reference it.
    op.add_column('managed_phases', sa.Column('definition_number', sa.Integer(), nullable=False, server_default='1'))
    op.drop_index('uq_managed_phases_open_root', table_name='managed_phases')
    op.create_index('uq_managed_phases_open_root', 'managed_phases', ['root'], unique=True, sqlite_where=OPEN_AFTER)
    table = op.create_table('phase_definitions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('phase_id', sa.String(36), sa.ForeignKey('managed_phases.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('definition', sa.JSON(), nullable=False),
        sa.Column('definition_sha256', sa.String(64), nullable=False),
        sa.Column('documents', sa.JSON(), nullable=False),
        sa.Column('origin', sa.String(20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('actor', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('phase_id', 'number'))
    # Earlier phases: their current definition becomes version 1, marked as migrated
    # (no reason or identity: they are not inferred).
    rows = op.get_bind().execute(sa.text(
        'SELECT id, definition, definition_sha256, documents FROM managed_phases ORDER BY created_at, id')).all()
    now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    op.bulk_insert(table, [{
        'id': str(uuid4()), 'phase_id': row.id, 'number': 1,
        'definition': json.loads(row.definition) if isinstance(row.definition, str) else row.definition,
        'definition_sha256': row.definition_sha256,
        'documents': json.loads(row.documents) if isinstance(row.documents, str) else row.documents,
        'origin': 'migrated', 'reason': None, 'actor': None, 'created_at': now} for row in rows])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM managed_phases WHERE status = 'ABANDONED'")).scalar():
        raise RuntimeError('Abandoned phases cannot be represented before 0011; keep this revision')
    if bind.execute(sa.text('SELECT count(*) FROM phase_definitions WHERE number > 1')).scalar():
        raise RuntimeError('Amended phase definitions cannot be represented before 0011; keep this revision')
    op.drop_table('phase_definitions')
    op.drop_index('uq_managed_phases_open_root', table_name='managed_phases')
    op.create_index('uq_managed_phases_open_root', 'managed_phases', ['root'], unique=True, sqlite_where=OPEN_BEFORE)
    # Native DROP COLUMN (SQLite ≥ 3.35), as in 0010.
    op.execute('ALTER TABLE managed_phases DROP COLUMN definition_number')
