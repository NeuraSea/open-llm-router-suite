from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.repositories.models import PlatformApiKeyRecord
from enterprise_llm_proxy.services.api_keys import PlatformApiKey


class PostgresPlatformApiKeyRepository:
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: PlatformApiKey) -> PlatformApiKey:
        with self._session_factory() as session:
            db_record = PlatformApiKeyRecord(
                id=record.id,
                name=record.name,
                key_prefix=record.key_prefix,
                key_hash=record.key_hash,
                principal_id=record.principal.user_id,
                principal_email=record.principal.email,
                principal_name=record.principal.name,
                principal_role=record.principal.role,
                principal_team_ids=list(record.principal.team_ids),
                created_at=record.created_at,
            )
            session.merge(db_record)
            session.commit()
        return record

    def list_for_principal(self, principal_id: str) -> list[PlatformApiKey]:
        """List all API keys owned by a principal (newest first)."""
        with self._session_factory() as session:
            records = session.scalars(
                select(PlatformApiKeyRecord)
                .where(PlatformApiKeyRecord.principal_id == principal_id)
                .order_by(PlatformApiKeyRecord.created_at.desc())
            ).all()
            return [
                PlatformApiKey(
                    id=record.id,
                    principal=Principal(
                        user_id=record.principal_id,
                        email=record.principal_email,
                        name=record.principal_name,
                        team_ids=list(record.principal_team_ids),
                        role=record.principal_role,
                    ),
                    name=record.name,
                    key_prefix=record.key_prefix,
                    key_hash=record.key_hash,
                    created_at=record.created_at,
                )
                for record in records
            ]

    def delete(self, key_id: str, principal_id: str) -> bool:
        """Delete a key by ID, only if owned by principal_id. Returns True if deleted."""
        with self._session_factory() as session:
            result = session.execute(
                delete(PlatformApiKeyRecord).where(
                    PlatformApiKeyRecord.id == key_id,
                    PlatformApiKeyRecord.principal_id == principal_id,
                )
            )
            session.commit()
            return result.rowcount > 0

    def find_by_hash(self, key_hash: str) -> PlatformApiKey | None:
        with self._session_factory() as session:
            record = session.scalars(
                select(PlatformApiKeyRecord).where(PlatformApiKeyRecord.key_hash == key_hash)
            ).first()
            if record is None:
                return None
            return PlatformApiKey(
                id=record.id,
                principal=Principal(
                    user_id=record.principal_id,
                    email=record.principal_email,
                    name=record.principal_name,
                    team_ids=list(record.principal_team_ids),
                    role=record.principal_role,
                ),
                name=record.name,
                key_prefix=record.key_prefix,
                key_hash=record.key_hash,
                created_at=record.created_at,
            )
