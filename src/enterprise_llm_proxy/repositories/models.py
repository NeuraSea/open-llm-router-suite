from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from enterprise_llm_proxy.repositories.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProviderCredentialRecord(Base):
    __tablename__ = "provider_credentials"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    auth_kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_alias: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_principal_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    visibility: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    concurrent_leases: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    max_concurrency: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    billing_model: Mapped[str | None] = mapped_column(String, nullable=True)
    quota_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    billing_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    catalog_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class QuotaRecord(Base):
    __tablename__ = "quotas"

    scope_type: Mapped[str] = mapped_column(String, primary_key=True)
    scope_id: Mapped[str] = mapped_column(Text, primary_key=True)
    limit: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class UsageEventRecord(Base):
    __tablename__ = "usage_events"

    request_id: Mapped[str] = mapped_column(Text, primary_key=True)
    principal_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    principal_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_profile: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    credential_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class UsageEventTeamRecord(Base):
    __tablename__ = "usage_event_teams"

    request_id: Mapped[str] = mapped_column(
        ForeignKey("usage_events.request_id", ondelete="CASCADE"),
        primary_key=True,
    )
    team_id: Mapped[str] = mapped_column(Text, primary_key=True, index=True)


class PlatformApiKeyRecord(Base):
    __tablename__ = "platform_api_keys"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    principal_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    principal_email: Mapped[str] = mapped_column(Text, nullable=False)
    principal_name: Mapped[str] = mapped_column(Text, nullable=False)
    principal_role: Mapped[str] = mapped_column(String, nullable=False)
    principal_team_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ConsumedJtiRecord(Base):
    __tablename__ = "consumed_jtis"

    jti: Mapped[str] = mapped_column(Text, primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class CliAuthStateRecord(Base):
    __tablename__ = "cli_auth_state"

    kind: Mapped[str] = mapped_column(String, nullable=False)  # "pending_login" or "pending_code"
    key: Mapped[str] = mapped_column(Text, primary_key=True)  # login_id or auth_code
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class RevokedTokenRecord(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(Text, primary_key=True)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class OAuthPendingStateRecord(Base):
    __tablename__ = "oauth_pending_state"

    state_key: Mapped[str] = mapped_column(Text, primary_key=True)
    principal_id: Mapped[str] = mapped_column(Text, nullable=False)
    code_verifier: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class CustomModelRecord(Base):
    __tablename__ = "custom_model_entries"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    model_profile: Mapped[str] = mapped_column(Text, nullable=False)
    upstream_model: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    auth_modes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    supported_clients: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class IssuedTokenRecord(Base):
    __tablename__ = "issued_tokens"

    jti: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    principal_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    client: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
