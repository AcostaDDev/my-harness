"""Owner-adopted task replacement links for persistent correction budgets."""
from alembic import op
import sqlalchemy as sa

revision = '0037_task_lineage'
down_revision = '0036_knowledge_exchange'
branch_labels = depends_on = None
OLD_KINDS = ('part_of', 'criterion_of', 'depends_on', 'addresses', 'supersedes')


def change(kinds):
    connection = op.get_bind()
    triggers = connection.execute(sa.text(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'knowledge_revision_links'")).all()
    for name, _ in triggers:
        op.execute(f'DROP TRIGGER "{name}"')
    with op.batch_alter_table('knowledge_revision_links') as batch:
        batch.drop_constraint('ck_knowledge_link_kind', type_='check')
        batch.create_check_constraint('ck_knowledge_link_kind', f'kind IN {kinds}')
    for _, sql in triggers:
        op.execute(sql)


def upgrade():
    change((*OLD_KINDS, 'replaces'))


def downgrade():
    if op.get_bind().execute(sa.text(
            "SELECT count(*) FROM knowledge_revision_links WHERE kind = 'replaces'")).scalar():
        raise RuntimeError('Task replacement evidence cannot be represented before 0037')
    change(OLD_KINDS)
