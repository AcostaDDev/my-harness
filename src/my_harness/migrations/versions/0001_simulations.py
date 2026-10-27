"""Atomic result of a local H0.3 simulation."""
from alembic import op
import sqlalchemy as sa

revision = "0001_simulations"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "simulations",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("simulations")
