"""Derived `run-projection-1` projection for the run views (P010-T003, D142).

Additive: creates the tables and fills them by decoding each existing history once (formats 1–8) with the current
codec. Does not modify `managed_runs.history_json`. The downgrade only drops derived tables.
"""
from alembic import op
import sqlalchemy as sa

revision = '0023_run_projection'
down_revision = '0022_project_preparation'
branch_labels = None
depends_on = None


def _run():
    """Column of each derived table; its FK is never shared between tables."""
    return sa.Column('run_id', sa.String(36), sa.ForeignKey('managed_runs.id'), primary_key=True)


def upgrade():
    tables = {
        'run_projections': op.create_table('run_projections',
            _run(),
            sa.Column('projection', sa.String(20), nullable=False),
            sa.Column('history_sha256', sa.String(64), nullable=False),
            sa.Column('history_status', sa.String(40), nullable=False),
            sa.Column('task_json', sa.Text(), nullable=True),
            sa.Column('attempts', sa.Integer(), nullable=False),
            sa.Column('executor_attempts', sa.Integer(), nullable=False),
            sa.Column('cycle_count', sa.Integer(), nullable=False),
            sa.Column('stop_count', sa.Integer(), nullable=False),
            sa.Column('stop_stage', sa.Text(), nullable=True),
            sa.Column('stop_reason', sa.Text(), nullable=True),
            sa.Column('acceptance_json', sa.Text(), nullable=True)),
        'run_projection_stops': op.create_table('run_projection_stops',
            _run(),
            sa.Column('ordinal', sa.Integer(), primary_key=True),
            sa.Column('stage', sa.Text(), nullable=False),
            sa.Column('reason', sa.Text(), nullable=False)),
        'run_projection_cycles': op.create_table('run_projection_cycles',
            _run(),
            sa.Column('number', sa.Integer(), primary_key=True),
            sa.Column('verdict', sa.Text(), nullable=True),
            sa.Column('fingerprint', sa.Text(), nullable=False),
            sa.Column('changed_paths_json', sa.Text(), nullable=False),
            sa.Column('diff_sha256', sa.String(64), nullable=False),
            sa.Column('diff_bytes', sa.Integer(), nullable=False),
            sa.Column('provenance_json', sa.Text(), nullable=True),
            sa.Column('review_json', sa.Text(), nullable=True),
            sa.Column('formatting_json', sa.Text(), nullable=True),
            sa.Column('validation_json', sa.Text(), nullable=False),
            sa.Column('validation_evidence_json', sa.Text(), nullable=False),
            sa.Column('validation_run_id', sa.Text(), nullable=True),
            sa.Column('validation_source_attempt_id', sa.Text(), nullable=True)),
        'run_projection_diff_chunks': op.create_table('run_projection_diff_chunks',
            _run(),
            sa.Column('cycle', sa.Integer(), primary_key=True),
            sa.Column('chunk', sa.Integer(), primary_key=True),
            sa.Column('data', sa.LargeBinary(), nullable=False)),
        'run_projection_reports': op.create_table('run_projection_reports',
            _run(),
            sa.Column('cycle', sa.Integer(), primary_key=True),
            sa.Column('entry', sa.Integer(), primary_key=True),
            sa.Column('report', sa.Integer(), primary_key=True),
            sa.Column('command_id', sa.Text(), nullable=True),
            sa.Column('summary_json', sa.Text(), nullable=False),
            sa.Column('original_base64', sa.Text(), nullable=True),
            sa.Column('sha256', sa.String(64), nullable=True),
            sa.Column('size_bytes', sa.Integer(), nullable=True),
            sa.Column('case_count', sa.Integer(), nullable=False)),
        'run_projection_cases': op.create_table('run_projection_cases',
            _run(),
            sa.Column('cycle', sa.Integer(), primary_key=True),
            sa.Column('entry', sa.Integer(), primary_key=True),
            sa.Column('report', sa.Integer(), primary_key=True),
            sa.Column('ordinal', sa.Integer(), primary_key=True),
            sa.Column('case_json', sa.Text(), nullable=False)),
    }
    from my_harness.storage.run_projection import rows
    bind = op.get_bind()
    # One history at a time: the backfill does not load all histories at once.
    for run_id in bind.execute(sa.text('SELECT id FROM managed_runs ORDER BY id')).scalars().all():
        history_json = bind.execute(sa.text('SELECT history_json FROM managed_runs WHERE id = :id'),
                                    {'id': run_id}).scalar_one()
        for name, items in rows(run_id, history_json).items():
            if items:
                op.bulk_insert(tables[name], items)


def downgrade():
    for name in ('run_projection_cases', 'run_projection_reports', 'run_projection_diff_chunks',
                 'run_projection_cycles', 'run_projection_stops', 'run_projections'):
        op.drop_table(name)
