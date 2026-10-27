"""H6.4: per-attempt metrics materialized with their result; backfilling earlier attempts is explicit."""
from alembic import op
import sqlalchemy as sa

revision = '0014_attempt_metrics'
down_revision = '0013_bootstrap'
branch_labels = None
depends_on = None

TOKENS = ('input_tokens', 'cache_read_tokens', 'cache_write_tokens', 'output_tokens', 'reasoning_tokens')


def upgrade():
    op.create_table('attempt_metrics',
        sa.Column('attempt_id', sa.String(36), sa.ForeignKey('managed_attempts.id'), primary_key=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('managed_runs.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('phase_code', sa.String(), nullable=False),
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column('purpose', sa.String(20), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('provider', sa.String(20), nullable=True),
        sa.Column('adapter_version', sa.String(40), nullable=True),
        sa.Column('cli_version', sa.String(80), nullable=True),
        sa.Column('requested_model', sa.String(200), nullable=True),
        sa.Column('requested_effort', sa.String(40), nullable=True),
        sa.Column('reported_models', sa.JSON(), nullable=True),
        sa.Column('reported_effort', sa.String(40), nullable=True),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('verdict', sa.String(40), nullable=True),
        sa.Column('executor_round', sa.Integer(), nullable=False),
        sa.Column('accounting', sa.String(20), nullable=True),
        sa.Column('input_semantics', sa.String(30), nullable=True),
        *(sa.Column(name, sa.Integer(), nullable=True) for name in TOKENS),
        sa.Column('uncached_input_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('turns', sa.Integer(), nullable=True),
        sa.Column('tool_calls', sa.Integer(), nullable=True),
        sa.Column('tools', sa.JSON(), nullable=True),
        sa.Column('permission_denials', sa.Integer(), nullable=True),
        sa.Column('wall_ms', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('api_duration_ms', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('started_at', sa.String(40), nullable=False),
        sa.Column('finished_at', sa.String(40), nullable=True),
        sa.Column('day', sa.String(10), nullable=False),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('normalization', sa.String(20), nullable=True),
        sa.Column('catalog', sa.String(20), nullable=False),
        sa.Column('provenance', sa.JSON(), nullable=False),
        sa.Column('diagnostics', sa.JSON(), nullable=False),
        sa.Column('recorded_at', sa.String(40), nullable=False))
    op.create_index('ix_attempt_metrics_scope', 'attempt_metrics', ['root', 'phase_code', 'task_id'])
    op.create_index('ix_attempt_metrics_run', 'attempt_metrics', ['run_id', 'number'], unique=True)
    op.create_table('attempt_model_metrics',
        sa.Column('attempt_id', sa.String(36), sa.ForeignKey('attempt_metrics.attempt_id'), primary_key=True),
        sa.Column('model', sa.String(200), primary_key=True),
        *(sa.Column(name, sa.Integer(), nullable=True) for name in TOKENS),
        sa.Column('cost_usd', sa.Float(), nullable=True))


def downgrade():
    # Derived data: the backfill rebuilds them from result_json (terminal-2 seals its counters). Only
    # what was read from a stdout before 0014 might not be rebuilt if that stream is later retired (H5.3).
    if op.get_bind().execute(sa.text("SELECT count(*) FROM attempt_metrics WHERE source = 'backfill' "
                                     "AND diagnostics LIKE '%stream_verified%'")).scalar():
        raise RuntimeError('Stream-derived attempt metrics cannot be represented before 0014; keep this revision')
    op.drop_table('attempt_model_metrics')
    op.drop_index('ix_attempt_metrics_run', 'attempt_metrics')
    op.drop_index('ix_attempt_metrics_scope', 'attempt_metrics')
    op.drop_table('attempt_metrics')
