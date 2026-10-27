"""P011-T007: global language preferences and the visual language frozen per job (D166).

Additive: creates the singleton `product_preferences` row with the factory values en/en and its event table, and
adds the nullable `managed_jobs.language_context`. Earlier jobs keep null: their language was not recorded.
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = '0024_product_preferences'
down_revision = '0023_run_projection'
branch_labels = None
depends_on = None


def upgrade():
    preferences = op.create_table('product_preferences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('format', sa.String(40), nullable=False),
        sa.Column('ui_language', sa.String(2), nullable=False),
        sa.Column('default_work_language', sa.String(2), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_product_preferences_singleton'),
        sa.CheckConstraint("ui_language IN ('en', 'es')", name='ck_product_preferences_ui_language'),
        sa.CheckConstraint("default_work_language IN ('en', 'es')", name='ck_product_preferences_work_language'))
    op.create_table('product_preference_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False, unique=True),
        sa.Column('idempotency_key', sa.String(200), nullable=False, unique=True),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False))
    op.bulk_insert(preferences, [{
        'id': 1, 'format': 'product-preferences-1', 'ui_language': 'en', 'default_work_language': 'en', 'version': 1,
        'updated_at': datetime.now(timezone.utc).isoformat(timespec='microseconds')}])
    # Additive ALTER: do not rebuild the parent table of locks, processes and commits with foreign_keys=ON.
    op.execute('ALTER TABLE managed_jobs ADD COLUMN language_context JSON')


def downgrade():
    # Without a recorded change the preferences never left en/en, so every frozen job language is that factory
    # value: dropping it loses nothing that an explicit choice made. A recorded change refuses the downgrade.
    if op.get_bind().execute(sa.text('SELECT count(*) FROM product_preference_events')).scalar():
        raise RuntimeError('Language preferences cannot be represented before 0024; keep this revision')
    op.drop_column('managed_jobs', 'language_context')
    op.drop_table('product_preference_events')
    op.drop_table('product_preferences')
