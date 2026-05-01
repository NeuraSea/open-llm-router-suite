from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


class CredentialState(str, Enum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    RATE_LIMITED = "rate_limited"
    DISABLED = "disabled"


class CredentialVisibility(str, Enum):
    PRIVATE = "private"
    ENTERPRISE_POOL = "enterprise_pool"
    SHARED_OPT_IN = "shared_opt_in"


@dataclass(frozen=True)
class ProviderCredential:
    id: str
    provider: str
    auth_kind: str
    account_id: str
    scopes: list[str]
    state: CredentialState
    expires_at: datetime | None
    cooldown_until: datetime | None
    access_token: str | None
    refresh_token: str | None
    owner_principal_id: str | None = None
    visibility: CredentialVisibility = CredentialVisibility.ENTERPRISE_POOL
    source: str | None = None
    last_selected_at: datetime | None = None
    concurrent_leases: int = 0
    max_concurrency: int = 1
    billing_model: str | None = None
    quota_info: dict | None = None
    billing_info: dict | None = None
    provider_alias: str | None = None
    catalog_info: dict | None = None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "provider": self.provider,
            "auth_kind": self.auth_kind,
            "account_id": self.account_id,
            "provider_alias": self.provider_alias,
            "scopes": self.scopes,
            "state": self.state.value,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "owner_principal_id": self.owner_principal_id,
            "visibility": self.visibility.value,
            "source": self.source,
            "max_concurrency": self.max_concurrency,
            "concurrent_leases": self.concurrent_leases,
            "billing_model": self.billing_model,
            "quota_info": self.quota_info,
            "billing_info": self.billing_info,
            "catalog_info": self.catalog_info,
        }

    def replace(self, **changes: object) -> "ProviderCredential":
        return replace(self, **changes)
