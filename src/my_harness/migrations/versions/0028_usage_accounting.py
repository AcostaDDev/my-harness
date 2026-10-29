"""P001-T003 / D257: additive invocation accounting records. No backfill or repricing in this migration."""
from alembic import op
import sqlalchemy as sa

revision = '0028_usage_accounting'
down_revision = '0027_profile_proposals'
branch_labels = None
depends_on = None

TABLES = ('valuation_cohort_members', 'valuation_cohorts', 'usage_valuation_lines', 'usage_valuations',
          'usage_components', 'usage_captures', 'usage_invocations', 'metrics_references')


def upgrade():
    op.create_table('usage_invocations',
        sa.Column('id', sa.String(80), primary_key=True),
        sa.Column('source_kind', sa.String(40), nullable=False),
        sa.Column('source_id', sa.String(36), nullable=False),
        sa.Column('attempt_id', sa.String(36), sa.ForeignKey('managed_attempts.id'), nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('managed_runs.id'), nullable=True),
        sa.Column('preparation_id', sa.String(36), sa.ForeignKey('project_preparation_operations.id'), nullable=True),
        sa.Column('preparation_step_id', sa.String(36), sa.ForeignKey('project_preparation_steps.id'), nullable=True),
        sa.Column('operation_id', sa.String(36), sa.ForeignKey('configuration_operations.id'), nullable=True),
        sa.Column('request_id', sa.String(36), nullable=True),
        sa.Column('root', sa.String(), nullable=True),
        sa.Column('project_id', sa.String(80), nullable=True),
        sa.Column('phase_code', sa.String(), nullable=True),
        sa.Column('task_id', sa.String(), nullable=True),
        sa.Column('purpose', sa.String(40), nullable=False),
        sa.Column('role', sa.String(40), nullable=False),
        sa.Column('agent', sa.String(20), nullable=True),
        sa.Column('requested_model', sa.String(200), nullable=True),
        sa.Column('requested_effort', sa.String(40), nullable=True),
        sa.Column('versions', sa.JSON(), nullable=False),
        sa.Column('binding', sa.JSON(), nullable=True),
        sa.Column('binding_sha256', sa.String(64), nullable=True),
        sa.Column('launch', sa.String(20), nullable=False),
        sa.Column('outcome', sa.String(40), nullable=True),
        sa.Column('started_at', sa.String(40), nullable=False),
        sa.Column('finished_at', sa.String(40), nullable=True),
        sa.Column('recorded_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('source_kind', 'source_id'),
        sa.CheckConstraint("source_kind IN ('managed_attempt', 'preparation_step', 'configuration_assistance')",
                           name='ck_usage_invocation_source'),
        sa.CheckConstraint("launch IN ('pending', 'not_invoked', 'observed', 'unknown_execution')",
                           name='ck_usage_invocation_launch'),
        sa.CheckConstraint("(source_kind = 'managed_attempt' AND attempt_id = source_id AND run_id IS NOT NULL "
                           "AND preparation_step_id IS NULL AND operation_id IS NULL) OR "
                           "(source_kind = 'preparation_step' AND preparation_step_id = source_id "
                           "AND preparation_id IS NOT NULL AND attempt_id IS NULL AND operation_id IS NULL) OR "
                           "(source_kind = 'configuration_assistance' AND operation_id = source_id "
                           "AND attempt_id IS NULL AND preparation_step_id IS NULL)", name='ck_usage_invocation_link'))
    op.create_index('ix_usage_invocations_scope', 'usage_invocations', ['root', 'phase_code', 'task_id'])
    op.create_index('ix_usage_invocations_started', 'usage_invocations', ['started_at'])
    op.create_table('usage_captures',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('invocation_id', sa.String(80), sa.ForeignKey('usage_invocations.id'), nullable=False),
        sa.Column('version', sa.String(40), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('document', sa.JSON(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('evidence_digest', sa.String(64), nullable=True),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('recorded_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('invocation_id', 'version', 'digest'))
    op.create_table('usage_components',
        sa.Column('capture_id', sa.Integer(), sa.ForeignKey('usage_captures.id'), primary_key=True),
        sa.Column('key', sa.String(250), primary_key=True),
        sa.Column('grain', sa.String(20), nullable=False),
        sa.Column('parent_key', sa.String(250), nullable=True),
        sa.Column('inclusion', sa.String(20), nullable=True),
        sa.Column('reported_model', sa.String(200), nullable=True),
        sa.Column('model_source', sa.String(20), nullable=True),
        sa.Column('semantics', sa.String(40), nullable=True),
        sa.Column('coverage', sa.String(20), nullable=False),
        *(sa.Column(name, sa.Integer(), nullable=True) for name in (
            'input_tokens', 'cache_read_tokens', 'cache_write_tokens', 'write_5m', 'write_1h', 'output_tokens',
            'reasoning_tokens')),
        sa.Column('reasons', sa.JSON(), nullable=False))
    op.create_table('metrics_references',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('format', sa.String(40), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('provider', sa.String(40), nullable=True),
        sa.Column('product', sa.String(80), nullable=True),
        sa.Column('model', sa.String(200), nullable=True),
        sa.Column('observed_at', sa.String(40), nullable=True),
        sa.Column('recorded_at', sa.String(40), nullable=False),
        sa.CheckConstraint("kind IN ('model_identity', 'tariff', 'bundle')", name='ck_metrics_reference_kind'))
    op.create_table('usage_valuations',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('invocation_id', sa.String(80), sa.ForeignKey('usage_invocations.id'), nullable=False),
        sa.Column('capture_id', sa.Integer(), sa.ForeignKey('usage_captures.id'), nullable=False),
        sa.Column('origin', sa.String(20), nullable=False),
        sa.Column('normalization', sa.String(40), nullable=False),
        sa.Column('calculator', sa.String(40), nullable=False),
        sa.Column('profile_digest', sa.String(64), nullable=False),
        sa.Column('reference_set_digest', sa.String(64), sa.ForeignKey('metrics_references.id'), nullable=False),
        sa.Column('basis', sa.String(40), nullable=False),
        sa.Column('scenario_digest', sa.String(64), nullable=False),
        sa.Column('evidence_digest', sa.String(64), nullable=False),
        sa.Column('scenario', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('unit', sa.String(80), nullable=False),
        sa.Column('scheme', sa.String(80), nullable=False),
        sa.Column('amount', sa.String(200), nullable=True),
        sa.Column('known_subtotal', sa.String(200), nullable=True),
        sa.Column('exact_sum', sa.Text(), nullable=True),
        sa.Column('rounding_adjustment', sa.Text(), nullable=True),
        sa.Column('counterfactual', sa.Boolean(), nullable=False),
        sa.Column('retrospective', sa.Boolean(), nullable=False),
        sa.Column('reasons', sa.JSON(), nullable=False),
        sa.Column('warnings', sa.JSON(), nullable=False),
        sa.Column('selected_components', sa.JSON(), nullable=False),
        sa.Column('discrepancy', sa.JSON(), nullable=True),
        sa.Column('supersedes', sa.String(64), sa.ForeignKey('usage_valuations.id'), nullable=True),
        sa.Column('recorded_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('invocation_id', 'capture_id', 'normalization', 'calculator', 'profile_digest',
                            'reference_set_digest', 'basis', 'scenario_digest'),
        sa.CheckConstraint("status IN ('complete', 'incomplete', 'unsupported')", name='ck_usage_valuation_status'),
        sa.CheckConstraint("origin IN ('admission', 'backfill', 'repricing')", name='ck_usage_valuation_origin'))
    op.create_table('usage_valuation_lines',
        sa.Column('valuation_id', sa.String(64), sa.ForeignKey('usage_valuations.id'), primary_key=True),
        sa.Column('number', sa.Integer(), primary_key=True),
        sa.Column('component_key', sa.String(250), nullable=False),
        sa.Column('category', sa.String(40), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('rate', sa.JSON(), nullable=False),
        sa.Column('factors', sa.JSON(), nullable=False),
        sa.Column('included_adjustments', sa.JSON(), nullable=False),
        sa.Column('tariff_reference', sa.String(64), sa.ForeignKey('metrics_references.id'), nullable=False),
        sa.Column('identity_reference', sa.String(64), sa.ForeignKey('metrics_references.id'), nullable=True),
        sa.Column('rate_case', sa.String(200), nullable=False),
        sa.Column('exact_amount', sa.Text(), nullable=False))
    op.create_table('valuation_cohorts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False, unique=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('idempotency_key', sa.String(200), nullable=False, unique=True),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('selection', sa.JSON(), nullable=False),
        sa.Column('selection_digest', sa.String(64), nullable=False),
        sa.Column('scenario', sa.JSON(), nullable=True),
        sa.Column('scenario_digest', sa.String(64), nullable=True),
        sa.Column('reference_set_digest', sa.String(64), sa.ForeignKey('metrics_references.id'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('expected', sa.Integer(), nullable=False),
        sa.Column('built', sa.Integer(), nullable=False),
        sa.Column('cursor', sa.String(80), nullable=True),
        sa.Column('report', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('closed_at', sa.String(40), nullable=True),
        sa.CheckConstraint("kind IN ('backfill', 'repricing')", name='ck_valuation_cohort_kind'),
        sa.CheckConstraint("status IN ('BUILDING', 'CLOSED')", name='ck_valuation_cohort_status'))
    op.create_table('valuation_cohort_members',
        sa.Column('cohort_id', sa.String(36), sa.ForeignKey('valuation_cohorts.id'), primary_key=True),
        sa.Column('invocation_id', sa.String(80), sa.ForeignKey('usage_invocations.id'), primary_key=True),
        sa.Column('basis', sa.String(40), primary_key=True),
        sa.Column('valuation_id', sa.String(64), sa.ForeignKey('usage_valuations.id'), nullable=True),
        sa.Column('reason', sa.String(80), nullable=True),
        sa.Column('recorded_at', sa.String(40), nullable=False),
        sa.CheckConstraint('(valuation_id IS NULL) <> (reason IS NULL)', name='ck_valuation_cohort_member'))


def downgrade():
    bind = op.get_bind()
    if any(bind.execute(sa.text(f'SELECT count(*) FROM {table}')).scalar() for table in TABLES):
        raise RuntimeError('Accounting records cannot be represented before 0028; keep this revision')
    op.drop_index('ix_usage_invocations_started', 'usage_invocations')
    op.drop_index('ix_usage_invocations_scope', 'usage_invocations')
    for table in TABLES:
        op.drop_table(table)
