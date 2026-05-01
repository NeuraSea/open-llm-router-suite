from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260327_03"
down_revision = "20260327_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.Text(), primary_key=True, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("revoked_tokens")
