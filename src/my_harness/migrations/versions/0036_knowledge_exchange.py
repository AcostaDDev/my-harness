"""D294 project-scoped document exchange evidence and checkout writer ownership."""
from alembic import op
import sqlalchemy as sa

revision = '0036_knowledge_exchange'
down_revision = '0035_permissions'
branch_labels = depends_on = None
TRIGGERS = {}
for action in ('update', 'delete'):
    name = f'knowledge_exchange_no_{action}'
    TRIGGERS[name] = f"CREATE TRIGGER {name} BEFORE {action.upper()} ON knowledge_exchange_records BEGIN SELECT RAISE(ABORT, 'knowledge exchange is immutable'); END"
TRIGGERS['knowledge_exchange_no_replace'] = """CREATE TRIGGER knowledge_exchange_no_replace BEFORE INSERT ON
knowledge_exchange_records WHEN EXISTS (SELECT 1 FROM knowledge_exchange_records WHERE id = NEW.id OR
(project_id = NEW.project_id AND record_key = NEW.record_key)) BEGIN SELECT RAISE(ABORT, 'knowledge exchange is immutable'); END"""


def upgrade():
    op.create_table('knowledge_exchange_records', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('knowledge_projects.id'), nullable=False),
        sa.Column('record_key', sa.String(240), nullable=False), sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False), sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False), sa.UniqueConstraint('project_id', 'record_key'))
    with op.batch_alter_table('checkout_locks') as batch:
        batch.drop_constraint('ck_checkout_lock_owner', type_='check')
        batch.add_column(sa.Column('exchange_id', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_checkout_exchange', 'knowledge_exchange_records', ['exchange_id'], ['id'])
        batch.create_unique_constraint('uq_checkout_exchange', ['exchange_id'])
        batch.create_check_constraint('ck_checkout_lock_owner',
            '(job_id IS NOT NULL) + (preparation_id IS NOT NULL) + (exchange_id IS NOT NULL) = 1')
    for sql in TRIGGERS.values():
        op.execute(sql)


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM knowledge_exchange_records')).scalar():
        raise RuntimeError('Knowledge exchange evidence cannot be represented before 0036')
    for name in TRIGGERS:
        op.execute(f'DROP TRIGGER {name}')
    with op.batch_alter_table('checkout_locks') as batch:
        batch.drop_constraint('ck_checkout_lock_owner', type_='check')
        batch.drop_constraint('uq_checkout_exchange', type_='unique')
        batch.drop_constraint('fk_checkout_exchange', type_='foreignkey')
        batch.drop_column('exchange_id')
        batch.create_check_constraint('ck_checkout_lock_owner', '(job_id IS NOT NULL) != (preparation_id IS NOT NULL)')
    op.drop_table('knowledge_exchange_records')
