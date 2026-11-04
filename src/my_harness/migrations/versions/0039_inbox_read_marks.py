"""P002-T017: durable read marks for the rebuildable inbox."""
from alembic import op
import sqlalchemy as sa

revision = '0039_inbox_read_marks'
down_revision = '0038_autonomous_runs'
branch_labels = depends_on = None

INDEXES = (
    ('managed_events', ('kind', 'run_id', 'sequence')),
    ('phase_events', ('kind', 'phase_id', 'sequence')),
    ('trace_events', ('kind', 'root')),
    ('autonomous_events', ('kind', 'run_id', 'id')),
)


def upgrade():
    op.create_table('inbox_read_marks',
                    sa.Column('item_id', sa.String(160), primary_key=True),
                    sa.Column('read_at', sa.String(40), nullable=False))
    for table, columns in INDEXES:
        op.create_index(f'ix_{table}_inbox', table, list(columns))


def downgrade():
    for table, _ in INDEXES:
        op.drop_index(f'ix_{table}_inbox', table_name=table)
    op.drop_table('inbox_read_marks')
