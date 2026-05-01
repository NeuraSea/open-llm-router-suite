from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260327_02"
down_revision = "20260319_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consumed_jtis",
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )

    op.create_table(
        "cli_auth_state",
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_cli_auth_state_expires_at", "cli_auth_state", ["expires_at"])

    op.create_table(
        "oauth_pending_state",
        sa.Column("state_key", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("state_key"),
    )
    op.create_index("ix_oauth_pending_state_expires_at", "oauth_pending_state", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_oauth_pending_state_expires_at", table_name="oauth_pending_state")
    op.drop_table("oauth_pending_state")

    op.drop_index("ix_cli_auth_state_expires_at", table_name="cli_auth_state")
    op.drop_table("cli_auth_state")

    op.drop_table("consumed_jtis")
