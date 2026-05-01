from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260319_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("auth_kind", sa.String(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("owner_principal_id", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("last_selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("concurrent_leases", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_concurrency", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_credentials_provider_auth_kind_state",
        "provider_credentials",
        ["provider", "auth_kind", "state"],
    )
    op.create_index(
        "ix_provider_credentials_owner_principal_id",
        "provider_credentials",
        ["owner_principal_id"],
    )
    op.create_index("ix_provider_credentials_visibility", "provider_credentials", ["visibility"])
    op.create_index(
        "ix_provider_credentials_cooldown_until",
        "provider_credentials",
        ["cooldown_until"],
    )

    op.create_table(
        "quotas",
        sa.Column("scope_type", sa.String(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scope_type", "scope_id"),
    )

    op.create_table(
        "usage_events",
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("model_profile", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("credential_id", sa.Text(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index("ix_usage_events_principal_id", "usage_events", ["principal_id"])
    op.create_index("ix_usage_events_credential_id", "usage_events", ["credential_id"])
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"])
    op.create_index(
        "ix_usage_events_principal_id_status",
        "usage_events",
        ["principal_id", "status"],
    )

    op.create_table(
        "usage_event_teams",
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("team_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["usage_events.request_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("request_id", "team_id"),
    )
    op.create_index("ix_usage_event_teams_team_id", "usage_event_teams", ["team_id"])

    op.create_table(
        "platform_api_keys",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("principal_email", sa.Text(), nullable=False),
        sa.Column("principal_name", sa.Text(), nullable=False),
        sa.Column("principal_role", sa.String(), nullable=False),
        sa.Column("principal_team_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_platform_api_keys_principal_id", "platform_api_keys", ["principal_id"])


def downgrade() -> None:
    op.drop_index("ix_platform_api_keys_principal_id", table_name="platform_api_keys")
    op.drop_table("platform_api_keys")

    op.drop_index("ix_usage_event_teams_team_id", table_name="usage_event_teams")
    op.drop_table("usage_event_teams")

    op.drop_index("ix_usage_events_principal_id_status", table_name="usage_events")
    op.drop_index("ix_usage_events_created_at", table_name="usage_events")
    op.drop_index("ix_usage_events_credential_id", table_name="usage_events")
    op.drop_index("ix_usage_events_principal_id", table_name="usage_events")
    op.drop_table("usage_events")

    op.drop_table("quotas")

    op.drop_index("ix_provider_credentials_cooldown_until", table_name="provider_credentials")
    op.drop_index("ix_provider_credentials_visibility", table_name="provider_credentials")
    op.drop_index(
        "ix_provider_credentials_owner_principal_id",
        table_name="provider_credentials",
    )
    op.drop_index(
        "ix_provider_credentials_provider_auth_kind_state",
        table_name="provider_credentials",
    )
    op.drop_table("provider_credentials")
