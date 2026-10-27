"""Opt-in observation and atomic events of the H1.3 index."""
from alembic import op
import sqlalchemy as sa

revision = "0003_legacy_observation"
down_revision = "0002_legacy_index"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("legacy_sources", sa.Column("watch_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("legacy_sources", sa.Column("diagnostic", sa.Text(), nullable=True))
    op.create_table("legacy_events",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("root", sa.String(), sa.ForeignKey("legacy_sources.root", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sqlite_autoincrement=True,
    )


def downgrade():
    op.drop_table("legacy_events")
    op.drop_column("legacy_sources", "diagnostic")
    op.drop_column("legacy_sources", "watch_enabled")
