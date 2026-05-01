from __future__ import annotations

from enterprise_llm_proxy.services.quotas import QuotaRule
from enterprise_llm_proxy.repositories.models import QuotaRecord
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class PostgresQuotaRepository:
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def set_quota(self, *, scope_type: str, scope_id: str, limit: int) -> QuotaRule:
        with self._session_factory() as session:
            record = session.get(QuotaRecord, {"scope_type": scope_type, "scope_id": scope_id})
            if record is None:
                record = QuotaRecord(scope_type=scope_type, scope_id=scope_id, limit=limit)
                session.add(record)
            else:
                record.limit = limit
            session.commit()
            return QuotaRule(scope_type=record.scope_type, scope_id=record.scope_id, limit=record.limit)

    def list_quotas(self) -> list[QuotaRule]:
        with self._session_factory() as session:
            records = session.scalars(
                select(QuotaRecord).order_by(QuotaRecord.scope_type, QuotaRecord.scope_id)
            ).all()
        return [QuotaRule(scope_type=item.scope_type, scope_id=item.scope_id, limit=item.limit) for item in records]

    def get_quota(self, *, scope_type: str, scope_id: str) -> QuotaRule | None:
        with self._session_factory() as session:
            record = session.get(QuotaRecord, {"scope_type": scope_type, "scope_id": scope_id})
            if record is None:
                return None
            return QuotaRule(scope_type=record.scope_type, scope_id=record.scope_id, limit=record.limit)
