"""Separate managed authority, jobs and exclusion H2.2."""
from alembic import op
import sqlalchemy as sa

revision = "0004_managed_queue"
down_revision = "0003_legacy_observation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("managed_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("root", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("phase_id", sa.String(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("versions_json", sa.Text(), nullable=False),
        sa.Column("history_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("revisions", sa.Integer(), nullable=False),
        sa.Column("revision_limit", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_table("managed_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("managed_runs.id"), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("owner_token", sa.String(36), nullable=True),
        sa.Column("heartbeat_at", sa.String(40), nullable=True),
        sa.Column("lease_until", sa.String(40), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("finished_at", sa.String(40), nullable=True),
        sa.Column("diagnostic", sa.Text(), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_table("checkout_locks",
        sa.Column("root", sa.String(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("managed_jobs.id"), nullable=False, unique=True),
    )
    op.create_table("managed_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("managed_runs.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("versions_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("finished_at", sa.String(40), nullable=True),
        sa.UniqueConstraint("run_id", "number"),
    )
    op.create_table("managed_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("managed_runs.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("recorded_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("run_id", "sequence"),
        sqlite_autoincrement=True,
    )


def downgrade():
    for table in ("managed_events", "managed_attempts", "checkout_locks", "managed_jobs", "managed_runs"):
        op.drop_table(table)
