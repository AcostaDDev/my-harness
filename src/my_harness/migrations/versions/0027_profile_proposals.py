"""D224: an intake registration has no executable composition or profile."""
from alembic import op
import sqlalchemy as sa

revision = '0027_profile_proposals'
down_revision = '0026_configuration'
branch_labels = None
depends_on = None


def checked_rebuild(nullable):
    # SQLite retains deferred DROP-parent counters even after Alembic restores the same ids.
    # Check all actual references before clearing those counters; never disable foreign_keys.
    op.execute('PRAGMA defer_foreign_keys=ON')
    with op.batch_alter_table('registered_projects') as batch:
        batch.alter_column('composition', existing_type=sa.String(64), nullable=nullable)
        batch.alter_column('profile', existing_type=sa.String(64), nullable=nullable)
    if op.get_bind().exec_driver_sql('PRAGMA foreign_key_check').first() is not None:
        raise RuntimeError('Profile intake migration found invalid foreign keys')
    op.execute('PRAGMA defer_foreign_keys=OFF')


def upgrade():
    checked_rebuild(True)


def downgrade():
    bind = op.get_bind()
    if (bind.execute(sa.text(
            'SELECT count(*) FROM registered_projects WHERE composition IS NULL OR profile IS NULL')).scalar()
            or bind.execute(sa.text("SELECT count(*) FROM managed_runs WHERE "
                                    "json_extract(context_json, '$.capabilities') = 'project-intake-1'")).scalar()
            or bind.execute(sa.text("SELECT count(*) FROM planning_proposals WHERE kind = 'profile'")).scalar()):
        raise RuntimeError('Profile intake registrations require 0027; keep this revision')
    checked_rebuild(False)
