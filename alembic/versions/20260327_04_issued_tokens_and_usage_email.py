from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260327_04"
down_revision = "20260327_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "issued_tokens",
        sa.Column("jti", sa.Text(), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("client", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_issued_tokens_principal_id", "issued_tokens", ["principal_id"])
    op.create_index("ix_issued_tokens_kind", "issued_tokens", ["kind"])
    op.add_column("usage_events", sa.Column("principal_email", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_issued_tokens_kind", "issued_tokens")
    op.drop_index("ix_issued_tokens_principal_id", "issued_tokens")
    op.drop_table("issued_tokens")
    op.drop_column("usage_events", "principal_email")
