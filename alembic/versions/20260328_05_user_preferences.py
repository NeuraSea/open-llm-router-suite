"""user preferences table

Revision ID: 20260328_05
Revises: bca2a7b69d22
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20260328_05'
down_revision = 'bca2a7b69d22'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_preferences',
        sa.Column('user_id', sa.Text(), nullable=False, primary_key=True),
        sa.Column('default_model', sa.Text(), nullable=True),
        sa.Column('routing_config', JSONB(), nullable=False, server_default='{}'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('user_preferences')
