"""Managed mode activation and provenance of the legacy history H2.5."""
from alembic import op
import sqlalchemy as sa

revision = "0007_managed_activation"
down_revision = "0006_git_commits"
branch_labels = None
depends_on = None

LIVE = sa.text("status IN ('PREPARING', 'ACTIVE', 'REVERTING')")


def upgrade():
    op.create_table("managed_activations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("root", sa.String(), nullable=False),
        sa.Column("repository_key", sa.String(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("preview_sha256", sa.String(64), nullable=False),
        sa.Column("legacy_stopped", sa.Text(), nullable=False),
        sa.Column("rules_json", sa.Text(), nullable=False),
        sa.Column("marker", sa.Text(), nullable=False),
        sa.Column("marker_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_root", sa.String(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=True),
        sa.Column("manifest_sha256", sa.String(64), nullable=True),
        sa.Column("owner_token", sa.String(36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("activated_at", sa.String(40), nullable=True),
        sa.Column("finished_at", sa.String(40), nullable=True),
        sa.Column("diagnostic", sa.Text(), nullable=True),
        sa.Column("revert_reason", sa.Text(), nullable=True),
        sa.Column("export_path", sa.String(), nullable=True),
        sa.Column("export_sha256", sa.String(64), nullable=True),
    )
    op.create_index("uq_managed_activations_live_root", "managed_activations", ["root"], unique=True,
                    sqlite_where=LIVE)
    op.create_index("uq_managed_activations_live_repository", "managed_activations", ["repository_key"],
                    unique=True, sqlite_where=LIVE)
    with op.batch_alter_table("managed_jobs") as batch:
        batch.add_column(sa.Column("activation_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_managed_jobs_activation", "managed_activations", ["activation_id"], ["id"])


def downgrade():
    with op.batch_alter_table("managed_jobs") as batch:
        batch.drop_constraint("fk_managed_jobs_activation", type_="foreignkey")
        batch.drop_column("activation_id")
    op.drop_index("uq_managed_activations_live_repository", table_name="managed_activations")
    op.drop_index("uq_managed_activations_live_root", table_name="managed_activations")
    op.drop_table("managed_activations")
