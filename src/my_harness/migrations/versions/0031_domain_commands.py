"""P002-T005 / D286: outcome record of typed domain commands, insert-only.

One row per accepted mutation, written in the mutation's own transaction, and one per recorded refusal. A partial
unique index keeps one accepted outcome per idempotency key and principal scope. The opener of a knowledge draft is
its accepted `knowledge.draft.open` row. No backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = '0031_domain_commands'
down_revision = '0030_structured_knowledge'
branch_labels = None
depends_on = None

PRINCIPALS = ('owner', 'harness', 'agent')
CHANNELS = ('api', 'graph', 'internal', 'broker')
ORIGINS = ('owner_confirmed', 'owner_delegated', 'harness_deterministic')
_ABORT = "SELECT RAISE(ABORT, 'domain_commands: outcome records are immutable')"
TRIGGERS = {
    'domain_commands_no_update': f'CREATE TRIGGER domain_commands_no_update BEFORE UPDATE ON domain_commands '
                                 f'BEGIN {_ABORT}; END',
    'domain_commands_no_delete': f'CREATE TRIGGER domain_commands_no_delete BEFORE DELETE ON domain_commands '
                                 f'BEGIN {_ABORT}; END',
    # REPLACE deletes the conflicting row without firing delete triggers; refuse the insertion instead.
    'domain_commands_no_replace': (
        'CREATE TRIGGER domain_commands_no_replace BEFORE INSERT ON domain_commands WHEN EXISTS (SELECT 1 FROM '
        'domain_commands WHERE id = NEW.id OR command_id = NEW.command_id OR outcome = \'ACCEPTED\' AND '
        'NEW.outcome = \'ACCEPTED\' AND knowledge_project_id = NEW.knowledge_project_id AND scope = NEW.scope AND '
        f'idempotency_key = NEW.idempotency_key) BEGIN {_ABORT}; END'),
}


def upgrade():
    op.create_table('domain_commands',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('command_id', sa.String(36), nullable=False, unique=True),
        sa.Column('knowledge_project_id', sa.String(36), sa.ForeignKey('knowledge_projects.id'), nullable=True),
        sa.Column('operation_id', sa.String(80), nullable=False),
        sa.Column('operation_version', sa.Integer(), nullable=False),
        sa.Column('schema_sha256', sa.String(64), nullable=True),
        sa.Column('catalogue_sha256', sa.String(64), nullable=False),
        sa.Column('principal', sa.String(10), nullable=False),
        sa.Column('channel', sa.String(10), nullable=False),
        sa.Column('caller', sa.JSON(), nullable=False),
        sa.Column('actor', sa.JSON(), nullable=False),
        sa.Column('origin', sa.String(30), nullable=True),
        sa.Column('scope', sa.String(200), nullable=False),
        sa.Column('idempotency_key', sa.String(200), nullable=True),
        sa.Column('request_sha256', sa.String(64), nullable=True),
        sa.Column('outcome', sa.String(10), nullable=False),
        sa.Column('refusal_code', sa.String(60), nullable=True),
        sa.Column('capability', sa.JSON(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('draft_id', sa.String(36), nullable=True),
        sa.Column('revision_id', sa.String(36), nullable=True),
        sa.Column('recorded_at', sa.String(40), nullable=False),
        sa.CheckConstraint(f'principal IN {PRINCIPALS}', name='ck_domain_command_principal'),
        sa.CheckConstraint(f'channel IN {CHANNELS}', name='ck_domain_command_channel'),
        sa.CheckConstraint(f'origin IS NULL OR origin IN {ORIGINS}', name='ck_domain_command_origin'),
        sa.CheckConstraint(
            "outcome = 'ACCEPTED' AND refusal_code IS NULL AND result IS NOT NULL AND capability IS NOT NULL "
            "AND knowledge_project_id IS NOT NULL AND idempotency_key IS NOT NULL AND request_sha256 IS NOT NULL "
            "AND schema_sha256 IS NOT NULL "
            "OR outcome = 'REFUSED' AND refusal_code IS NOT NULL AND result IS NULL AND draft_id IS NULL "
            "AND revision_id IS NULL", name='ck_domain_command_outcome'),
        sa.ForeignKeyConstraint(['knowledge_project_id', 'draft_id'],
                                ['knowledge_revisions.project_id', 'knowledge_revisions.id'],
                                name='fk_domain_commands_draft'),
        sa.ForeignKeyConstraint(['knowledge_project_id', 'revision_id'],
                                ['knowledge_revisions.project_id', 'knowledge_revisions.id'],
                                name='fk_domain_commands_revision'))
    op.create_index('uq_domain_commands_key', 'domain_commands', ['knowledge_project_id', 'scope', 'idempotency_key'],
                    unique=True, sqlite_where=sa.text("outcome = 'ACCEPTED'"))
    op.create_index('ix_domain_commands_draft', 'domain_commands', ['draft_id', 'operation_id'])
    for statement in TRIGGERS.values():
        op.execute(statement)


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT count(*) FROM domain_commands')).scalar():
        raise RuntimeError('Domain command outcomes cannot be represented before 0031; keep this revision')
    for name in TRIGGERS:
        op.execute(f'DROP TRIGGER {name}')
    op.drop_table('domain_commands')
