from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from enterprise_llm_proxy.repositories.models import IssuedTokenRecord


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class IssuedTokenRow:
    jti: str
    kind: str
    principal_id: str
    email: str
    client: str | None
    model: str | None
    issued_at: datetime
    expires_at: datetime


class PostgresIssuedTokenRepository:
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(
        self,
        *,
        jti: str,
        kind: str,
        principal_id: str,
        email: str,
        client: str | None,
        model: str | None,
        issued_at: datetime,
        expires_at: datetime,
    ) -> None:
        rec = IssuedTokenRecord(
            jti=jti,
            kind=kind,
            principal_id=principal_id,
            email=email,
            client=client,
            model=model,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        with self._session_factory() as session:
            session.merge(rec)
            session.commit()

    def list_active(self, *, kind: str | None = None) -> list[IssuedTokenRow]:
        now = _utcnow()
        with self._session_factory() as session:
            q = session.query(IssuedTokenRecord).filter(IssuedTokenRecord.expires_at > now)
            if kind is not None:
                q = q.filter(IssuedTokenRecord.kind == kind)
            rows = q.order_by(IssuedTokenRecord.issued_at.desc()).all()
            return [
                IssuedTokenRow(
                    jti=r.jti,
                    kind=r.kind,
                    principal_id=r.principal_id,
                    email=r.email,
                    client=r.client,
                    model=r.model,
                    issued_at=r.issued_at,
                    expires_at=r.expires_at,
                )
                for r in rows
            ]


class _InMemoryIssuedTokenRepository:
    def __init__(self) -> None:
        self._tokens: dict[str, IssuedTokenRow] = {}

    def record(
        self,
        *,
        jti: str,
        kind: str,
        principal_id: str,
        email: str,
        client: str | None,
        model: str | None,
        issued_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._tokens[jti] = IssuedTokenRow(
            jti=jti,
            kind=kind,
            principal_id=principal_id,
            email=email,
            client=client,
            model=model,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def list_active(self, *, kind: str | None = None) -> list[IssuedTokenRow]:
        now = _utcnow()
        result = []
        for t in self._tokens.values():
            expires = t.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires > now and (kind is None or t.kind == kind):
                result.append(t)
        return result
