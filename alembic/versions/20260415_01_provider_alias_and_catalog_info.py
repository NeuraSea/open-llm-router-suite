"""add provider alias and catalog info to provider credentials

Revision ID: 20260415_01
Revises: 20260329_02
Create Date: 2026-04-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260415_01"
down_revision = "20260329_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_credentials", sa.Column("provider_alias", sa.String(), nullable=True))
    op.add_column("provider_credentials", sa.Column("catalog_info", postgresql.JSONB(), nullable=True))
    op.create_index(
        "ix_provider_credentials_provider_alias_enterprise",
        "provider_credentials",
        ["provider_alias"],
        unique=True,
        postgresql_where=sa.text(
            "provider_alias IS NOT NULL "
            "AND provider IN ('openai_compat', 'anthropic_compat') "
            "AND visibility = 'enterprise_pool'"
        ),
    )
    op.create_index(
        "ix_provider_credentials_owner_principal_id_provider_alias",
        "provider_credentials",
        ["owner_principal_id", "provider_alias"],
        unique=True,
        postgresql_where=sa.text(
            "provider_alias IS NOT NULL "
            "AND provider IN ('openai_compat', 'anthropic_compat')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_credentials_owner_principal_id_provider_alias",
        table_name="provider_credentials",
    )
    op.drop_index(
        "ix_provider_credentials_provider_alias_enterprise",
        table_name="provider_credentials",
    )
    op.drop_column("provider_credentials", "catalog_info")
    op.drop_column("provider_credentials", "provider_alias")
