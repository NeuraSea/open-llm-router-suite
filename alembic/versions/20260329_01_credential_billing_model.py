"""credential billing model columns

Revision ID: 20260329_01
Revises: 20260328_05
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20260329_01'
down_revision = '20260328_05'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('provider_credentials', sa.Column('billing_model', sa.String(), nullable=True))
    op.add_column('provider_credentials', sa.Column('quota_info', JSONB(), nullable=True))
    op.add_column('provider_credentials', sa.Column('billing_info', JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('provider_credentials', 'billing_info')
    op.drop_column('provider_credentials', 'quota_info')
    op.drop_column('provider_credentials', 'billing_model')
