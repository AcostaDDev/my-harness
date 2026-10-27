"""Rebuildable H1.1 observation index, separate from simulations."""
from alembic import op
import sqlalchemy as sa

revision = "0002_legacy_index"
down_revision = "0001_simulations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "legacy_sources",
        sa.Column("root", sa.String(), primary_key=True, nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "legacy_runs",
        sa.Column("root", sa.String(), sa.ForeignKey("legacy_sources.root", ondelete="CASCADE"),
                  primary_key=True, nullable=False),
        sa.Column("path", sa.String(), primary_key=True, nullable=False),
        sa.Column("identity", sa.String(), nullable=False),
    )
    op.create_table(
        "legacy_artifacts",
        sa.Column("root", sa.String(), sa.ForeignKey("legacy_sources.root", ondelete="CASCADE"),
                  primary_key=True, nullable=False),
        sa.Column("path", sa.String(), primary_key=True, nullable=False),
        sa.Column("run_path", sa.String(), nullable=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("diagnostic", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["root", "run_path"], ["legacy_runs.root", "legacy_runs.path"]),
    )


def downgrade():
    op.drop_table("legacy_artifacts")
    op.drop_table("legacy_runs")
    op.drop_table("legacy_sources")
