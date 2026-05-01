"""add custom_model_entries table

Revision ID: 20260329_02
Revises: 20260329_01
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260329_02'
down_revision = '20260329_01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'custom_model_entries',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('display_name', sa.Text(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model_profile', sa.Text(), nullable=False),
        sa.Column('upstream_model', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('auth_modes', postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column('supported_clients', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_custom_model_entries_provider', 'custom_model_entries', ['provider'])


def downgrade():
    op.drop_index('ix_custom_model_entries_provider', table_name='custom_model_entries')
    op.drop_table('custom_model_entries')
