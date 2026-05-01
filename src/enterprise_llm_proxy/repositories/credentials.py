from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from enterprise_llm_proxy.domain.credentials import (
    CredentialState,
    CredentialVisibility,
    ProviderCredential,
)
from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.repositories.models import ProviderCredentialRecord
from enterprise_llm_proxy.security import SecretCodec


class PostgresCredentialRepository:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        secret_codec: SecretCodec,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._secret_codec = secret_codec
        self._clock = clock or self._utcnow

    def list_credentials(self) -> list[ProviderCredential]:
        with self._session_factory() as session:
            records = session.scalars(
                select(ProviderCredentialRecord).order_by(ProviderCredentialRecord.account_id)
            ).all()
        return [self._to_domain(record) for record in records]

    def list_for_owner(self, owner_principal_id: str) -> list[ProviderCredential]:
        with self._session_factory() as session:
            records = session.scalars(
                select(ProviderCredentialRecord)
                .where(ProviderCredentialRecord.owner_principal_id == owner_principal_id)
                .order_by(ProviderCredentialRecord.account_id)
            ).all()
        return [self._to_domain(record) for record in records]

    def get_credential(self, credential_id: str) -> ProviderCredential | None:
        with self._session_factory() as session:
            record = session.get(ProviderCredentialRecord, credential_id)
            return self._to_domain(record) if record is not None else None

    def create_credential(
        self,
        *,
        provider: str,
        auth_kind: str,
        account_id: str,
        scopes: list[str],
        access_token: str | None,
        refresh_token: str | None,
        max_concurrency: int,
        provider_alias: str | None = None,
        expires_at: datetime | None = None,
        owner_principal_id: str | None = None,
        visibility: CredentialVisibility = CredentialVisibility.ENTERPRISE_POOL,
        source: str | None = None,
        billing_model: str | None = None,
        catalog_info: dict | None = None,
    ) -> ProviderCredential:
        now = self._clock()
        record = ProviderCredentialRecord(
            id=f"cred-{uuid4().hex[:10]}",
            provider=provider,
            auth_kind=auth_kind,
            account_id=account_id,
            provider_alias=provider_alias,
            scopes=list(scopes),
            state=CredentialState.ACTIVE.value,
            expires_at=expires_at,
            cooldown_until=None,
            access_token_encrypted=self._secret_codec.encode(access_token),
            refresh_token_encrypted=self._secret_codec.encode(refresh_token),
            owner_principal_id=owner_principal_id,
            visibility=visibility.value,
            source=source,
            last_selected_at=None,
            concurrent_leases=0,
            max_concurrency=max_concurrency,
            billing_model=billing_model,
            quota_info=None,
            billing_info=None,
            catalog_info=catalog_info,
            created_at=now,
            updated_at=now,
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._to_domain(record)

    def update_credential(self, credential: ProviderCredential) -> ProviderCredential:
        with self._session_factory() as session:
            record = session.get(ProviderCredentialRecord, credential.id)
            if record is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Credential not found",
                )
            self._apply_domain(record, credential)
            record.updated_at = self._clock()
            session.commit()
            session.refresh(record)
            return self._to_domain(record)

    def update_visibility(
        self,
        credential_id: str,
        *,
        visibility: CredentialVisibility,
    ) -> ProviderCredential:
        with self._session_factory() as session:
            record = session.get(ProviderCredentialRecord, credential_id)
            if record is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Credential not found",
                )
            record.visibility = visibility.value
            record.updated_at = self._clock()
            session.commit()
            session.refresh(record)
            return self._to_domain(record)

    def select(
        self,
        *,
        provider: str,
        auth_kind: str,
        provider_alias: str | None = None,
        upstream_model: str | None = None,
        principal: Principal | None = None,
        excluded_ids: set[str] | None = None,
    ) -> ProviderCredential | None:
        now = self._clock()
        with self._session_factory() as session:
            statement: Select[tuple[ProviderCredentialRecord]] = (
                select(ProviderCredentialRecord)
                .where(ProviderCredentialRecord.provider == provider)
                .where(ProviderCredentialRecord.auth_kind == auth_kind)
                .where(
                    or_(
                        and_(
                            ProviderCredentialRecord.state == CredentialState.ACTIVE.value,
                            or_(
                                ProviderCredentialRecord.cooldown_until.is_(None),
                                ProviderCredentialRecord.cooldown_until <= now,
                            ),
                        ),
                        and_(
                            ProviderCredentialRecord.state.in_(
                                [
                                    CredentialState.COOLDOWN.value,
                                    CredentialState.RATE_LIMITED.value,
                                ]
                            ),
                            ProviderCredentialRecord.cooldown_until <= now,
                        ),
                    )
                )
                .where(ProviderCredentialRecord.concurrent_leases < ProviderCredentialRecord.max_concurrency)
                .where(self._accessible_clause(principal))
                .order_by(
                    ProviderCredentialRecord.concurrent_leases.asc(),
                    ProviderCredentialRecord.last_selected_at.asc().nullsfirst(),
                )
                .with_for_update(skip_locked=True)
            )
            if excluded_ids:
                statement = statement.where(ProviderCredentialRecord.id.not_in(excluded_ids))
            if provider_alias is not None:
                statement = statement.where(ProviderCredentialRecord.provider_alias == provider_alias)

            records = session.scalars(statement).all()
            record = next(
                (
                    candidate
                    for candidate in records
                    if self._record_supports_upstream_model(candidate, upstream_model)
                ),
                None,
            )
            if record is None:
                session.rollback()
                return None

            record.state = CredentialState.ACTIVE.value
            record.cooldown_until = None
            record.concurrent_leases += 1
            record.last_selected_at = now
            record.updated_at = now
            session.commit()
            session.refresh(record)
            return self._to_domain(record)

    def mark_cooldown(self, credential_id: str, *, seconds: int) -> ProviderCredential | None:
        with self._session_factory() as session:
            record = session.get(ProviderCredentialRecord, credential_id, with_for_update=True)
            if record is None:
                return None
            record.state = CredentialState.COOLDOWN.value
            record.cooldown_until = self._clock().replace(microsecond=0) + timedelta(seconds=seconds)
            record.concurrent_leases = max(0, record.concurrent_leases - 1)
            record.updated_at = self._clock()
            session.commit()
            session.refresh(record)
            return self._to_domain(record)

    def mark_disabled(self, credential_id: str) -> ProviderCredential | None:
        with self._session_factory() as session:
            record = session.get(ProviderCredentialRecord, credential_id, with_for_update=True)
            if record is None:
                return None
            record.state = CredentialState.DISABLED.value
            record.cooldown_until = None
            record.concurrent_leases = max(0, record.concurrent_leases - 1)
            record.updated_at = self._clock()
            session.commit()
            session.refresh(record)
            return self._to_domain(record)

    def release(self, credential_id: str) -> None:
        with self._session_factory() as session:
            record = session.get(ProviderCredentialRecord, credential_id, with_for_update=True)
            if record is None:
                return
            record.concurrent_leases = max(0, record.concurrent_leases - 1)
            record.updated_at = self._clock()
            session.commit()

    def reset_stale_leases(self, *, max_age_seconds: int) -> int:
        cutoff = self._clock() - timedelta(seconds=max_age_seconds)
        now = self._clock()
        with self._session_factory() as session:
            records = session.scalars(
                select(ProviderCredentialRecord)
                .where(ProviderCredentialRecord.concurrent_leases > 0)
                .where(ProviderCredentialRecord.updated_at <= cutoff)
                .with_for_update(skip_locked=True)
            ).all()
            for record in records:
                record.concurrent_leases = 0
                record.updated_at = now
            if records:
                session.commit()
            else:
                session.rollback()
            return len(records)

    def delete_credential(self, credential_id: str) -> None:
        with self._session_factory() as session:
            record = session.get(ProviderCredentialRecord, credential_id)
            if record is not None:
                session.delete(record)
                session.commit()

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)

    def _accessible_clause(self, principal: Principal | None):
        clauses = [ProviderCredentialRecord.visibility == CredentialVisibility.ENTERPRISE_POOL.value]
        if principal is None:
            return or_(*clauses)
        clauses.append(ProviderCredentialRecord.owner_principal_id == principal.user_id)
        if principal.role == "admin":
            clauses.append(ProviderCredentialRecord.visibility == CredentialVisibility.SHARED_OPT_IN.value)
        return or_(*clauses)

    def _to_domain(self, record: ProviderCredentialRecord) -> ProviderCredential:
        return ProviderCredential(
            id=record.id,
            provider=record.provider,
            auth_kind=record.auth_kind,
            account_id=record.account_id,
            provider_alias=record.provider_alias,
            scopes=list(record.scopes),
            state=CredentialState(record.state),
            expires_at=record.expires_at,
            cooldown_until=record.cooldown_until,
            access_token=self._secret_codec.decode(record.access_token_encrypted),
            refresh_token=self._secret_codec.decode(record.refresh_token_encrypted),
            owner_principal_id=record.owner_principal_id,
            visibility=CredentialVisibility(record.visibility),
            source=record.source,
            last_selected_at=record.last_selected_at,
            concurrent_leases=record.concurrent_leases,
            max_concurrency=record.max_concurrency,
            billing_model=record.billing_model,
            quota_info=record.quota_info,
            billing_info=record.billing_info,
            catalog_info=record.catalog_info,
        )

    @staticmethod
    def _available_models_from_record(record: ProviderCredentialRecord) -> set[str]:
        raw_models: object = None
        if isinstance(record.catalog_info, dict):
            raw_models = record.catalog_info.get("available_models")
        if not isinstance(raw_models, list) and isinstance(record.quota_info, dict):
            raw_models = record.quota_info.get("available_models")
        if not isinstance(raw_models, list):
            return set()
        return {
            str(raw_model).strip()
            for raw_model in raw_models
            if str(raw_model).strip()
        }

    @classmethod
    def _record_supports_upstream_model(
        cls,
        record: ProviderCredentialRecord,
        upstream_model: str | None,
    ) -> bool:
        if not upstream_model:
            return True
        available_models = cls._available_models_from_record(record)
        if not available_models:
            return True
        return upstream_model in available_models

    def _apply_domain(
        self,
        record: ProviderCredentialRecord,
        credential: ProviderCredential,
    ) -> None:
        record.provider = credential.provider
        record.auth_kind = credential.auth_kind
        record.account_id = credential.account_id
        record.provider_alias = credential.provider_alias
        record.scopes = list(credential.scopes)
        record.state = credential.state.value
        record.expires_at = credential.expires_at
        record.cooldown_until = credential.cooldown_until
        record.access_token_encrypted = self._secret_codec.encode(credential.access_token)
        record.refresh_token_encrypted = self._secret_codec.encode(credential.refresh_token)
        record.owner_principal_id = credential.owner_principal_id
        record.visibility = credential.visibility.value
        record.source = credential.source
        record.last_selected_at = credential.last_selected_at
        record.concurrent_leases = credential.concurrent_leases
        record.max_concurrency = credential.max_concurrency
        record.billing_model = credential.billing_model
        record.quota_info = credential.quota_info
        record.billing_info = credential.billing_info
        record.catalog_info = credential.catalog_info
