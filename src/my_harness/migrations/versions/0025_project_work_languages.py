"""P011-T008: immutable work language per canonical project root and the language pair frozen per attempt (D167).

Additive: creates `project_work_languages`, one row per canonical root that is written once and never updated,
and adds the nullable `managed_attempts.language_context`. Earlier projects keep no row (work language not
confirmed, never inferred) and earlier attempts keep null.
"""
from alembic import op
import sqlalchemy as sa

revision = '0025_project_work_languages'
down_revision = '0024_product_preferences'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('project_work_languages',
        sa.Column('root', sa.String(), primary_key=True),
        sa.Column('format', sa.String(40), nullable=False),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('work_language', sa.String(2), nullable=False),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('confirmation', sa.JSON(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('confirmed_at', sa.String(40), nullable=False),
        sa.CheckConstraint("work_language IN ('en', 'es')", name='ck_project_work_languages_language'),
        sa.CheckConstraint("source IN ('registration', 'creation', 'toml', 'migration')",
                           name='ck_project_work_languages_source'))
    # Additive ALTER, as in 0024: the attempts table is not rebuilt.
    op.execute('ALTER TABLE managed_attempts ADD COLUMN language_context JSON')


def downgrade():
    # A confirmed work language is an explicit, immutable choice: it cannot be represented before 0025.
    if op.get_bind().execute(sa.text('SELECT count(*) FROM project_work_languages')).scalar():
        raise RuntimeError('Confirmed work languages cannot be represented before 0025; keep this revision')
    op.drop_column('managed_attempts', 'language_context')
    op.drop_table('project_work_languages')
