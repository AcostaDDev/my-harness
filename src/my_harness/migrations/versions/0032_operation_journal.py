"""P002-T006 / D287: operation journal behind `OperationPort` and correlated trace events.

`workflow_operations` holds one recoverable operation per key inside a graph thread, with its writer fence and links
to the domain command, managed attempt and accounting invocation it concerns; its status is a projection.
`trace_events` is ordered by its autoincrement id, deduplicated by `dedupe_key` and insert-only; `trace_artifacts`
keeps the masked content an event offloads, also insert-only. No backfill: 0.1.9 runs keep their own journals.
"""
from alembic import op
import sqlalchemy as sa

revision = '0032_operation_journal'
down_revision = '0031_domain_commands'
branch_labels = None
depends_on = None

STATUSES = ('INTENDED', 'COMPLETED', 'FAILED', 'UNCERTAIN', 'ABANDONED')
SOURCES = ('supplied', 'reported', 'derived', 'measured', 'absent')
_ABORT = "SELECT RAISE(ABORT, 'trace_events: events are immutable')"
_ARTIFACT_ABORT = "SELECT RAISE(ABORT, 'trace_artifacts: artifacts are immutable')"
TRIGGERS = {
    'trace_events_no_update': f'CREATE TRIGGER trace_events_no_update BEFORE UPDATE ON trace_events BEGIN {_ABORT}; END',
    'trace_events_no_delete': f'CREATE TRIGGER trace_events_no_delete BEFORE DELETE ON trace_events BEGIN {_ABORT}; END',
    # REPLACE deletes the conflicting row without firing delete triggers; refuse the insertion instead.
    'trace_events_no_replace': (
        'CREATE TRIGGER trace_events_no_replace BEFORE INSERT ON trace_events WHEN EXISTS (SELECT 1 FROM trace_events '
        f'WHERE id = NEW.id OR event_id = NEW.event_id OR dedupe_key = NEW.dedupe_key) BEGIN {_ABORT}; END'),
    'trace_artifacts_no_update': ('CREATE TRIGGER trace_artifacts_no_update BEFORE UPDATE ON trace_artifacts '
                                  f'BEGIN {_ARTIFACT_ABORT}; END'),
    'trace_artifacts_no_delete': ('CREATE TRIGGER trace_artifacts_no_delete BEFORE DELETE ON trace_artifacts '
                                  f'BEGIN {_ARTIFACT_ABORT}; END'),
    'trace_artifacts_no_replace': (
        'CREATE TRIGGER trace_artifacts_no_replace BEFORE INSERT ON trace_artifacts WHEN EXISTS (SELECT 1 FROM '
        f'trace_artifacts WHERE event_id = NEW.event_id AND sha256 = NEW.sha256) BEGIN {_ARTIFACT_ABORT}; END'),
}


def upgrade():
    op.create_table('workflow_operations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('thread_id', sa.String(80), sa.ForeignKey('graph_threads.id'), nullable=False),
        sa.Column('key', sa.String(80), nullable=False),
        sa.Column('root', sa.String(), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('parent_operation_id', sa.String(36), sa.ForeignKey('workflow_operations.id'), nullable=True),
        sa.Column('causation_event_id', sa.String(36), nullable=True),
        sa.Column('origin', sa.JSON(), nullable=True),
        sa.Column('refs', sa.JSON(), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('managed_jobs.id'), nullable=True),
        sa.Column('owner_token', sa.String(36), nullable=True),
        sa.Column('command_id', sa.String(36), sa.ForeignKey('domain_commands.command_id'), nullable=True),
        sa.Column('attempt_id', sa.String(36), sa.ForeignKey('managed_attempts.id'), nullable=True),
        sa.Column('invocation_id', sa.String(80), sa.ForeignKey('usage_invocations.id'), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('thread_id', 'key'),
        sa.CheckConstraint(f'status IN {STATUSES}', name='ck_workflow_operation_status'),
        sa.CheckConstraint("kind != 'agent_invocation' OR (attempt_id IS NOT NULL AND invocation_id IS NOT NULL "
                           "AND job_id IS NOT NULL AND owner_token IS NOT NULL)", name='ck_workflow_operation_writer'),
        sa.CheckConstraint("kind != 'domain_command' OR (command_id IS NOT NULL AND status = 'COMPLETED')",
                           name='ck_workflow_operation_command'))
    op.create_index('ix_workflow_operations_root', 'workflow_operations', ['root', 'thread_id'])
    op.create_index('ix_workflow_operations_status', 'workflow_operations', ['status'])
    op.create_index('uq_workflow_operations_attempt', 'workflow_operations', ['attempt_id'], unique=True,
                    sqlite_where=sa.text('attempt_id IS NOT NULL'))
    op.create_table('trace_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('event_id', sa.String(36), nullable=False, unique=True),
        sa.Column('dedupe_key', sa.String(200), nullable=False, unique=True),
        sa.Column('root', sa.String(), nullable=True),
        sa.Column('thread_id', sa.String(80), sa.ForeignKey('graph_threads.id'), nullable=True),
        sa.Column('operation_id', sa.String(36), sa.ForeignKey('workflow_operations.id'), nullable=True),
        sa.Column('invocation_id', sa.String(80), sa.ForeignKey('usage_invocations.id'), nullable=True),
        sa.Column('command_id', sa.String(36), sa.ForeignKey('domain_commands.command_id'), nullable=True),
        sa.Column('parent_event_id', sa.String(36), nullable=True),
        sa.Column('causation_id', sa.String(36), nullable=True),
        sa.Column('kind', sa.String(60), nullable=False),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('payload_sha256', sa.String(64), nullable=False),
        sa.Column('truncated', sa.Boolean(), nullable=False),
        sa.Column('redactions', sa.Integer(), nullable=False),
        sa.Column('recorded_at', sa.String(40), nullable=False),
        sa.CheckConstraint(f'source IN {SOURCES}', name='ck_trace_event_source'),
        sqlite_autoincrement=True)
    op.create_index('ix_trace_events_thread', 'trace_events', ['thread_id', 'id'])
    op.create_index('ix_trace_events_operation', 'trace_events', ['operation_id', 'id'])
    op.create_index('ix_trace_events_root', 'trace_events', ['root', 'id'])
    op.create_table('trace_artifacts',
        sa.Column('event_id', sa.String(36), sa.ForeignKey('trace_events.event_id'), primary_key=True),
        sa.Column('sha256', sa.String(64), primary_key=True),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('media', sa.String(80), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False))
    for statement in TRIGGERS.values():
        op.execute(statement)


def downgrade():
    bind = op.get_bind()
    for table in ('trace_artifacts', 'trace_events', 'workflow_operations'):
        if bind.execute(sa.text(f'SELECT count(*) FROM {table}')).scalar():
            raise RuntimeError('Operation journal records cannot be represented before 0032; keep this revision')
    for name in TRIGGERS:
        op.execute(f'DROP TRIGGER {name}')
    op.drop_table('trace_artifacts')
    op.drop_table('trace_events')
    op.drop_table('workflow_operations')
