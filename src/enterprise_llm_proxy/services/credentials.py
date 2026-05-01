from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable, Protocol
from uuid import uuid4

from fastapi import HTTPException, status

from enterprise_llm_proxy.domain.credentials import (
    CredentialState,
    CredentialVisibility,
    ProviderCredential,
)
from enterprise_llm_proxy.domain.models import Principal


class CredentialRefresher(Protocol):
    def refresh(self, provider: str, refresh_token: str | None) -> dict[str, object]:
        ...


class NoopCredentialRefresher:
    def refresh(self, provider: str, refresh_token: str | None) -> dict[str, object]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Credential refresher is not configured for {provider}",
        )


@dataclass(frozen=True)
class CredentialRouteBlock:
    reason: str
    state: CredentialState
    credential_count: int
    retry_at: datetime | None = None


class CredentialPoolService:
    def __init__(
        self,
        credentials: Iterable[ProviderCredential] | None = None,
        overlay_credentials: Iterable[ProviderCredential] | None = None,
        refresher: CredentialRefresher | None = None,
        repository=None,  # type: ignore[no-untyped-def]
    ) -> None:
        self._repository = repository
        self._credentials = {
            credential.id: credential for credential in (credentials or [])
        }
        self._overlay_credentials = {
            credential.id: credential for credential in (overlay_credentials or [])
        }
        self._refresher = refresher or NoopCredentialRefresher()

    def list_credentials(self) -> list[ProviderCredential]:
        repo_credentials = self._repository.list_credentials() if self._repository is not None else list(
            self._credentials.values()
        )
        return sorted(
            [*repo_credentials, *self._overlay_credentials.values()],
            key=lambda item: item.account_id,
        )

    def list_for_owner(self, owner_principal_id: str) -> list[ProviderCredential]:
        if self._repository is not None:
            return self._repository.list_for_owner(owner_principal_id)
        return sorted(
            [
                credential
                for credential in self._credentials.values()
                if credential.owner_principal_id == owner_principal_id
            ],
            key=lambda item: item.account_id,
        )

    def get_credential(self, credential_id: str) -> ProviderCredential | None:
        if credential_id in self._overlay_credentials:
            return self._overlay_credentials[credential_id]
        if self._repository is not None:
            return self._repository.get_credential(credential_id)
        return self._credentials.get(credential_id)

    def create_credential(
        self,
        *,
        provider: str,
        auth_kind: str,
        account_id: str,
        provider_alias: str | None = None,
        scopes: list[str],
        access_token: str | None,
        refresh_token: str | None,
        max_concurrency: int,
        expires_at: datetime | None = None,
        owner_principal_id: str | None = None,
        visibility: CredentialVisibility = CredentialVisibility.ENTERPRISE_POOL,
        source: str | None = None,
        billing_model: str | None = None,
        catalog_info: dict | None = None,
    ) -> ProviderCredential:
        if self._repository is not None:
            return self._repository.create_credential(
                provider=provider,
                auth_kind=auth_kind,
                account_id=account_id,
                provider_alias=provider_alias,
                scopes=scopes,
                access_token=access_token,
                refresh_token=refresh_token,
                max_concurrency=max_concurrency,
                expires_at=expires_at,
                owner_principal_id=owner_principal_id,
                visibility=visibility,
                source=source,
                billing_model=billing_model,
                catalog_info=catalog_info,
            )
        credential = ProviderCredential(
            id=f"cred-{uuid4().hex[:10]}",
            provider=provider,
            auth_kind=auth_kind,
            account_id=account_id,
            provider_alias=provider_alias,
            scopes=scopes,
            state=CredentialState.ACTIVE,
            expires_at=expires_at,
            cooldown_until=None,
            access_token=access_token,
            refresh_token=refresh_token,
            owner_principal_id=owner_principal_id,
            visibility=visibility,
            source=source,
            max_concurrency=max_concurrency,
            billing_model=billing_model,
            catalog_info=catalog_info,
        )
        self._credentials[credential.id] = credential
        return credential

    def refresh_credential(self, credential_id: str) -> ProviderCredential:
        credential = self.get_credential(credential_id)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )

        refreshed = self._refresher.refresh(credential.provider, credential.refresh_token)
        updated = credential.replace(
            access_token=refreshed.get("access_token", credential.access_token),
            expires_at=refreshed.get("expires_at", credential.expires_at),
            state=CredentialState(refreshed.get("state", credential.state.value)),
            cooldown_until=refreshed.get("cooldown_until", None),
        )
        if credential_id in self._overlay_credentials:
            self._overlay_credentials[credential_id] = updated
            return updated
        if self._repository is not None:
            return self._repository.update_credential(updated)
        self._credentials[credential_id] = updated
        return updated

    def update_visibility(
        self,
        credential_id: str,
        *,
        visibility: CredentialVisibility,
    ) -> ProviderCredential:
        if credential_id in self._overlay_credentials:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System credentials are managed by configuration",
            )
        if self._repository is not None:
            return self._repository.update_visibility(credential_id, visibility=visibility)
        credential = self._credentials.get(credential_id)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        updated = credential.replace(visibility=visibility)
        self._credentials[credential_id] = updated
        return updated

    def update_max_concurrency(
        self,
        credential_id: str,
        *,
        max_concurrency: int,
    ) -> ProviderCredential:
        if max_concurrency < 1:
            raise HTTPException(
                status_code=422,
                detail="max_concurrency must be greater than or equal to 1",
            )
        if credential_id in self._overlay_credentials:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System credentials are managed by configuration",
            )
        credential = self.get_credential(credential_id)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        updated = credential.replace(max_concurrency=max_concurrency)
        if self._repository is not None:
            return self._repository.update_credential(updated)
        self._credentials[credential_id] = updated
        return updated

    def update_credential(self, credential: ProviderCredential) -> ProviderCredential:
        if credential.id in self._overlay_credentials:
            self._overlay_credentials[credential.id] = credential
            return credential
        if self._repository is not None:
            return self._repository.update_credential(credential)
        self._credentials[credential.id] = credential
        return credential

    def select(
        self,
        *,
        provider: str,
        auth_kind: str,
        provider_alias: str | None = None,
        upstream_model: str | None = None,
        principal: Principal | None = None,
        excluded_ids: set[str] | None = None,
        prefer_overlay: bool = False,
    ) -> ProviderCredential | None:
        overlay_candidate = self._select_overlay(
            provider=provider,
            auth_kind=auth_kind,
            provider_alias=provider_alias,
            upstream_model=upstream_model,
            principal=principal,
            excluded_ids=excluded_ids,
        )
        if prefer_overlay and overlay_candidate is not None:
            return overlay_candidate
        if self._repository is not None:
            repository_candidate = self._repository.select(
                provider=provider,
                auth_kind=auth_kind,
                provider_alias=provider_alias,
                upstream_model=upstream_model,
                principal=principal,
                excluded_ids=excluded_ids,
            )
            if repository_candidate is not None:
                return repository_candidate
            return overlay_candidate
        now = datetime.now(UTC)
        candidates = [
            credential
            for credential in [*self._credentials.values(), *self._overlay_credentials.values()]
            if credential.provider == provider
            and credential.auth_kind == auth_kind
            and credential.provider_alias == provider_alias
            and credential.id not in (excluded_ids or set())
            and self._is_selectable(credential, now)
            and credential.concurrent_leases < credential.max_concurrency
            and self._is_accessible(credential, principal)
            and self._supports_upstream_model(credential, upstream_model)
        ]
        if not candidates:
            return None

        chosen = min(
            candidates,
            key=lambda item: (
                item.concurrent_leases,
                item.last_selected_at or datetime.min.replace(tzinfo=UTC),
            ),
        )
        updated = chosen.replace(
            state=CredentialState.ACTIVE,
            cooldown_until=None,
            last_selected_at=now,
            concurrent_leases=chosen.concurrent_leases + 1,
        )
        if chosen.id in self._overlay_credentials:
            self._overlay_credentials[chosen.id] = updated
        else:
            self._credentials[chosen.id] = updated
        return updated

    def has_available(
        self,
        *,
        provider: str,
        auth_kind: str,
        provider_alias: str | None = None,
        upstream_model: str | None = None,
        principal: Principal | None = None,
        excluded_ids: set[str] | None = None,
        prefer_overlay: bool = False,
    ) -> bool:
        overlay_available = self._has_available_overlay(
            provider=provider,
            auth_kind=auth_kind,
            provider_alias=provider_alias,
            upstream_model=upstream_model,
            principal=principal,
            excluded_ids=excluded_ids,
        )
        if prefer_overlay and overlay_available:
            return True

        now = datetime.now(UTC)
        if self._repository is not None:
            repo_credentials = self._repository.list_credentials()
        else:
            repo_credentials = list(self._credentials.values())
        repository_available = any(
            credential.provider == provider
            and credential.auth_kind == auth_kind
            and credential.provider_alias == provider_alias
            and credential.id not in (excluded_ids or set())
            and self._is_selectable(credential, now)
            and credential.concurrent_leases < credential.max_concurrency
            and self._is_accessible(credential, principal)
            and self._supports_upstream_model(credential, upstream_model)
            for credential in repo_credentials
        )
        return repository_available or overlay_available

    def diagnose_route_block(
        self,
        *,
        provider: str,
        auth_kind: str,
        provider_alias: str | None = None,
        upstream_model: str | None = None,
        principal: Principal | None = None,
    ) -> CredentialRouteBlock | None:
        now = datetime.now(UTC)
        matching = [
            credential
            for credential in self.list_credentials()
            if credential.provider == provider
            and credential.auth_kind == auth_kind
            and credential.provider_alias == provider_alias
            and self._is_accessible(credential, principal)
            and self._supports_upstream_model(credential, upstream_model)
        ]
        if not matching:
            return CredentialRouteBlock(
                reason="unbound",
                state=CredentialState.DISABLED,
                credential_count=0,
            )

        selectable = [
            credential
            for credential in matching
            if self._is_selectable(credential, now)
        ]
        saturated = [
            credential
            for credential in selectable
            if credential.concurrent_leases >= credential.max_concurrency
        ]
        if selectable and len(saturated) == len(selectable):
            return CredentialRouteBlock(
                reason="saturated",
                state=CredentialState.ACTIVE,
                credential_count=len(saturated),
            )

        blocked = [
            credential
            for credential in matching
            if self._is_temporarily_blocked(credential, now)
        ]
        if len(blocked) != len(matching):
            return None

        retry_at_candidates = [
            credential.cooldown_until
            for credential in blocked
            if credential.cooldown_until is not None and credential.cooldown_until > now
        ]
        retry_at = min(retry_at_candidates) if retry_at_candidates else None
        state = (
            CredentialState.COOLDOWN
            if retry_at is not None or any(credential.state == CredentialState.COOLDOWN for credential in blocked)
            else CredentialState.RATE_LIMITED
        )
        return CredentialRouteBlock(
            reason=state.value,
            state=state,
            credential_count=len(blocked),
            retry_at=retry_at,
        )

    def mark_cooldown(self, credential_id: str, *, seconds: int) -> ProviderCredential | None:
        if self._repository is not None:
            return self._repository.mark_cooldown(credential_id, seconds=seconds)
        if credential_id in self._overlay_credentials:
            credential = self._overlay_credentials.get(credential_id)
            if credential is None:
                return None
            updated = credential.replace(
                state=CredentialState.COOLDOWN,
                cooldown_until=datetime.now(UTC).replace(microsecond=0)
                + timedelta(seconds=seconds),
                concurrent_leases=max(0, credential.concurrent_leases - 1),
            )
            self._overlay_credentials[credential_id] = updated
            return updated
        credential = self._credentials.get(credential_id)
        if credential is None:
            return None
        updated = credential.replace(
            state=CredentialState.COOLDOWN,
            cooldown_until=datetime.now(UTC).replace(microsecond=0)
            + timedelta(seconds=seconds),
            concurrent_leases=max(0, credential.concurrent_leases - 1),
        )
        self._credentials[credential_id] = updated
        return updated

    def mark_disabled(self, credential_id: str) -> ProviderCredential | None:
        if self._repository is not None:
            return self._repository.mark_disabled(credential_id)
        if credential_id in self._overlay_credentials:
            credential = self._overlay_credentials.get(credential_id)
            if credential is None:
                return None
            updated = credential.replace(
                state=CredentialState.DISABLED,
                cooldown_until=None,
                concurrent_leases=max(0, credential.concurrent_leases - 1),
            )
            self._overlay_credentials[credential_id] = updated
            return updated
        credential = self._credentials.get(credential_id)
        if credential is None:
            return None
        updated = credential.replace(
            state=CredentialState.DISABLED,
            cooldown_until=None,
            concurrent_leases=max(0, credential.concurrent_leases - 1),
        )
        self._credentials[credential_id] = updated
        return updated

    def release(self, credential_id: str) -> None:
        if self._repository is not None:
            if credential_id in self._overlay_credentials:
                credential = self._overlay_credentials.get(credential_id)
                if credential is None:
                    return
                updated = credential.replace(
                    concurrent_leases=max(0, credential.concurrent_leases - 1),
                )
                self._overlay_credentials[credential_id] = updated
                return
            self._repository.release(credential_id)
            return
        credential = self._credentials.get(credential_id)
        if credential is not None:
            updated = credential.replace(
                concurrent_leases=max(0, credential.concurrent_leases - 1),
            )
            self._credentials[credential_id] = updated
            return
        credential = self._overlay_credentials.get(credential_id)
        if credential is None:
            return
        updated = credential.replace(
            concurrent_leases=max(0, credential.concurrent_leases - 1),
        )
        self._overlay_credentials[credential_id] = updated

    def reset_stale_leases(self, *, max_age_seconds: int) -> int:
        if self._repository is not None:
            return self._repository.reset_stale_leases(max_age_seconds=max_age_seconds)
        return 0

    def delete_credential(self, credential_id: str) -> None:
        if credential_id in self._overlay_credentials:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System credentials are managed by configuration",
            )
        if self._repository is not None:
            self._repository.delete_credential(credential_id)
            return
        self._credentials.pop(credential_id, None)

    def _select_overlay(
        self,
        *,
        provider: str,
        auth_kind: str,
        provider_alias: str | None = None,
        upstream_model: str | None = None,
        principal: Principal | None = None,
        excluded_ids: set[str] | None = None,
    ) -> ProviderCredential | None:
        now = datetime.now(UTC)
        candidates = [
            credential
            for credential in self._overlay_credentials.values()
            if credential.provider == provider
            and credential.auth_kind == auth_kind
            and credential.provider_alias == provider_alias
            and credential.id not in (excluded_ids or set())
            and self._is_selectable(credential, now)
            and credential.concurrent_leases < credential.max_concurrency
            and self._is_accessible(credential, principal)
            and self._supports_upstream_model(credential, upstream_model)
        ]
        if not candidates:
            return None

        chosen = min(
            candidates,
            key=lambda item: (
                item.concurrent_leases,
                item.last_selected_at or datetime.min.replace(tzinfo=UTC),
            ),
        )
        updated = chosen.replace(
            state=CredentialState.ACTIVE,
            cooldown_until=None,
            last_selected_at=now,
            concurrent_leases=chosen.concurrent_leases + 1,
        )
        self._overlay_credentials[chosen.id] = updated
        return updated

    def _has_available_overlay(
        self,
        *,
        provider: str,
        auth_kind: str,
        provider_alias: str | None = None,
        upstream_model: str | None = None,
        principal: Principal | None = None,
        excluded_ids: set[str] | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        return any(
            credential.provider == provider
            and credential.auth_kind == auth_kind
            and credential.provider_alias == provider_alias
            and credential.id not in (excluded_ids or set())
            and self._is_selectable(credential, now)
            and credential.concurrent_leases < credential.max_concurrency
            and self._is_accessible(credential, principal)
            and self._supports_upstream_model(credential, upstream_model)
            for credential in self._overlay_credentials.values()
        )

    @staticmethod
    def _is_selectable(credential: ProviderCredential, now: datetime) -> bool:
        if credential.state == CredentialState.ACTIVE:
            return credential.cooldown_until is None or credential.cooldown_until <= now
        if credential.state in {CredentialState.COOLDOWN, CredentialState.RATE_LIMITED}:
            return credential.cooldown_until is not None and credential.cooldown_until <= now
        return False

    @staticmethod
    def _is_temporarily_blocked(credential: ProviderCredential, now: datetime) -> bool:
        if credential.state == CredentialState.COOLDOWN:
            return credential.cooldown_until is None or credential.cooldown_until > now
        if credential.state == CredentialState.RATE_LIMITED:
            return credential.cooldown_until is None or credential.cooldown_until > now
        if credential.cooldown_until is not None and credential.cooldown_until > now:
            return True
        return False

    @staticmethod
    def _is_accessible(
        credential: ProviderCredential,
        principal: Principal | None,
    ) -> bool:
        if credential.visibility == CredentialVisibility.ENTERPRISE_POOL:
            return True
        if principal is None:
            return False
        if credential.owner_principal_id == principal.user_id:
            return True
        return credential.visibility == CredentialVisibility.SHARED_OPT_IN and principal.role == "admin"

    @staticmethod
    def _credential_available_models(credential: ProviderCredential) -> set[str]:
        raw_models: object = None
        if isinstance(credential.catalog_info, dict):
            raw_models = credential.catalog_info.get("available_models")
        if not isinstance(raw_models, list) and isinstance(credential.quota_info, dict):
            raw_models = credential.quota_info.get("available_models")
        if not isinstance(raw_models, list):
            return set()
        return {
            str(raw_model).strip()
            for raw_model in raw_models
            if str(raw_model).strip()
        }

    @classmethod
    def _supports_upstream_model(
        cls,
        credential: ProviderCredential,
        upstream_model: str | None,
    ) -> bool:
        if not upstream_model:
            return True
        available_models = cls._credential_available_models(credential)
        if not available_models:
            return True
        return upstream_model in available_models
