"""Immutable prompt versions, active pointers and activation audit."""
from alembic import op
import sqlalchemy as sa

revision = '0008_prompt_versions'
down_revision = '0007_managed_activation'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('prompt_heads',
        sa.Column('scope', sa.String(), primary_key=True),
        sa.Column('owner', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), primary_key=True),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('active_id', sa.String(), nullable=True))
    op.create_table('prompt_versions',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('owner', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('template', sa.Text(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))
    op.create_table('prompt_activations',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('owner', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('previous_id', sa.String(), nullable=True),
        sa.Column('version_id', sa.String(), sa.ForeignKey('prompt_versions.id'), nullable=False),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False))


def downgrade():
    op.drop_table('prompt_activations')
    op.drop_table('prompt_versions')
    op.drop_table('prompt_heads')
