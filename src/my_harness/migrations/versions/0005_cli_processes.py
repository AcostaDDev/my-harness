"""Durable process ownership and capture references H2.3."""
from alembic import op
import sqlalchemy as sa

revision = "0005_cli_processes"
down_revision = "0004_managed_queue"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("managed_jobs", sa.Column("process_owner", sa.JSON(), nullable=True))
    op.add_column("managed_jobs", sa.Column("owner_closed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("managed_processes",
        sa.Column("attempt_id", sa.String(36), sa.ForeignKey("managed_attempts.id"), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("managed_jobs.id"), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("identity", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("capture", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_table("managed_processes")
    with op.batch_alter_table("managed_jobs") as batch:
        batch.drop_column("owner_closed")
        batch.drop_column("process_owner")
