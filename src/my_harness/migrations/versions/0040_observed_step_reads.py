"""P002-T019 (D305, D310): keyset reads of observed steps per invocation.

Additive index only; no table, column or row changes and no backfill. Measured on a synthetic 5,000-step trace beside
150,000 and 600,000 other step events: the page p95 grows from 7.3 to 20.7 ms through the `(kind, root)` index and a
sort, and stays at 1.6 ms with this index.
"""
from alembic import op

revision = '0040_observed_step_reads'
down_revision = '0039_inbox_read_marks'
branch_labels = depends_on = None


def upgrade():
    op.create_index('ix_trace_events_invocation', 'trace_events', ['invocation_id', 'kind', 'id'])


def downgrade():
    op.drop_index('ix_trace_events_invocation', table_name='trace_events')
