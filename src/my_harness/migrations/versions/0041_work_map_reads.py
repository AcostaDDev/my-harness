"""P002-T020 (D311): indexed reads of the work-map projections.

Additive indexes only; no table, column or row changes and no backfill. `managed_runs` had no index on its checkout
root, so every root-scoped map query scanned all runs; the open-attempt partial index keeps the activity poll's
active-invocation query proportional to the attempts in flight; phase operations are read per phase and kind; each
circle's latest invocation uses ordered ledger ranges per role; conversation ownership filters chat candidates
and registered-project ranges cover root-NULL configuration assistance. Measurements are in docs/phase/P002-T020-work-map-api.md.
"""
from alembic import op
import sqlalchemy as sa

revision = '0041_work_map_reads'
down_revision = '0040_observed_step_reads'
branch_labels = depends_on = None
CIRCLES = {'ix_usage_invocations_circle_project': ['project_id', 'role', 'started_at', 'id'],
           'ix_usage_invocations_circle_root': ['root', 'role', 'started_at', 'id'],
           'ix_usage_invocations_circle_phase': ['root', 'phase_code', 'role', 'started_at', 'id'],
           'ix_usage_invocations_circle_task': ['root', 'phase_code', 'task_id', 'role', 'started_at', 'id']}


def upgrade():
    op.create_index('ix_managed_runs_scope', 'managed_runs', ['root', 'purpose', 'phase_id', 'task_id', 'created_at'])
    op.create_index('ix_managed_attempts_open', 'managed_attempts', ['run_id'],
                    sqlite_where=sa.text('result_json IS NULL'))
    op.create_index('ix_phase_operations_phase', 'phase_operations', ['phase_id', 'kind', 'created_at'])
    for name, columns in CIRCLES.items():
        op.create_index(name, 'usage_invocations', columns)


def downgrade():
    for name in CIRCLES:
        op.drop_index(name, table_name='usage_invocations')
    op.drop_index('ix_phase_operations_phase', table_name='phase_operations')
    op.drop_index('ix_managed_attempts_open', table_name='managed_attempts')
    op.drop_index('ix_managed_runs_scope', table_name='managed_runs')
