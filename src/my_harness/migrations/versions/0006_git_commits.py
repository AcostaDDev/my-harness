"""Intent/result of accepted commits H2.4."""
from alembic import op
import sqlalchemy as sa

revision = "0006_git_commits"
down_revision = "0005_cli_processes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("managed_commits",
        sa.Column("operation_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("managed_runs.id"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("managed_jobs.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("base_revision", sa.String(64), nullable=False),
        sa.Column("reviewed_fingerprint", sa.String(64), nullable=False),
        sa.Column("expected_tree", sa.String(64), nullable=False),
        sa.Column("expected_commit", sa.String(64), nullable=False),
        sa.Column("intent_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("commit_sha", sa.String(64), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("finished_at", sa.String(40), nullable=True),
    )
    op.create_index("uq_managed_commits_live", "managed_commits", ["run_id"], unique=True,
                    sqlite_where=sa.text("status IN ('INTENT', 'COMMITTED')"))


def downgrade():
    op.drop_index("uq_managed_commits_live", table_name="managed_commits")
    op.drop_table("managed_commits")
