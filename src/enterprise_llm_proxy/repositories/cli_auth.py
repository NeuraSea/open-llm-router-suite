from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.repositories.models import (
    CliAuthStateRecord,
    ConsumedJtiRecord,
    OAuthPendingStateRecord,
    RevokedTokenRecord,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PostgresCliAuthRepository:
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def consume_jti(self, *, jti: str, expires_at: datetime) -> bool:
        """Atomically mark JTI as consumed. Returns True if this was the first consumption."""
        stmt = pg_insert(ConsumedJtiRecord).values(
            jti=jti,
            expires_at=expires_at,
            consumed_at=_utcnow(),
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["jti"])
        with self._session_factory() as session:
            result = session.execute(stmt)
            session.commit()
            return result.rowcount == 1

    def put_pending_login(
        self,
        *,
        login_id: str,
        payload: dict,
        expires_at: datetime,
    ) -> None:
        record = CliAuthStateRecord(
            kind="pending_login",
            key=login_id,
            payload=_serialize_payload(payload),
            expires_at=expires_at,
        )
        with self._session_factory() as session:
            session.merge(record)
            session.commit()

    def get_pending_login(self, *, login_id: str) -> dict | None:
        now = _utcnow()
        with self._session_factory() as session:
            record = session.get(CliAuthStateRecord, login_id)
            if record is None:
                return None
            if record.expires_at.replace(tzinfo=UTC) <= now:
                session.delete(record)
                session.commit()
                return None
            return _deserialize_payload(dict(record.payload))

    def pop_pending_login(self, *, login_id: str) -> dict | None:
        now = _utcnow()
        with self._session_factory() as session:
            record = session.get(CliAuthStateRecord, login_id)
            if record is None:
                return None
            if record.expires_at.replace(tzinfo=UTC) <= now:
                session.delete(record)
                session.commit()
                return None
            payload = _deserialize_payload(dict(record.payload))
            session.delete(record)
            session.commit()
            return payload

    def put_pending_code(
        self,
        *,
        code: str,
        payload: dict,
        expires_at: datetime,
    ) -> None:
        record = CliAuthStateRecord(
            kind="pending_code",
            key=code,
            payload=_serialize_payload(payload),
            expires_at=expires_at,
        )
        with self._session_factory() as session:
            session.merge(record)
            session.commit()

    def pop_pending_code(self, *, code: str) -> dict | None:
        now = _utcnow()
        with self._session_factory() as session:
            record = session.get(CliAuthStateRecord, code)
            if record is None:
                return None
            if record.expires_at.replace(tzinfo=UTC) <= now:
                session.delete(record)
                session.commit()
                return None
            payload = _deserialize_payload(dict(record.payload))
            session.delete(record)
            session.commit()
            return payload

    def put_codex_oauth_principal(
        self, *, state: str, principal: Principal, expires_at: datetime
    ) -> None:
        record = CliAuthStateRecord(
            kind="codex_oauth_state",
            key=state,
            payload=_serialize_payload({"principal": principal}),
            expires_at=expires_at,
        )
        with self._session_factory() as session:
            session.merge(record)
            session.commit()

    def pop_codex_oauth_principal(self, *, state: str) -> Principal | None:
        now = _utcnow()
        with self._session_factory() as session:
            record = session.get(CliAuthStateRecord, state)
            if record is None:
                return None
            if record.expires_at.replace(tzinfo=UTC) <= now:
                session.delete(record)
                session.commit()
                return None
            payload = _deserialize_payload(dict(record.payload))
            session.delete(record)
            session.commit()
            return payload.get("principal")

    def sweep_expired(self) -> None:
        """Delete expired entries from both tables."""
        now = _utcnow()
        with self._session_factory() as session:
            session.execute(
                delete(CliAuthStateRecord).where(CliAuthStateRecord.expires_at <= now)
            )
            session.execute(
                delete(ConsumedJtiRecord).where(ConsumedJtiRecord.expires_at <= now)
            )
            session.commit()


class PostgresOAuthPendingRepository:
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def put_pending(
        self,
        *,
        state: str,
        principal_id: str,
        code_verifier: str,
        expires_at: datetime,
    ) -> None:
        record = OAuthPendingStateRecord(
            state_key=state,
            principal_id=principal_id,
            code_verifier=code_verifier,
            expires_at=expires_at,
        )
        with self._session_factory() as session:
            session.merge(record)
            session.commit()

    def pop_pending(self, state: str) -> tuple[str, str] | None:
        """Return (principal_id, code_verifier) and delete, or None if not found/expired."""
        now = _utcnow()
        with self._session_factory() as session:
            record = session.get(OAuthPendingStateRecord, state)
            if record is None:
                return None
            if record.expires_at.replace(tzinfo=UTC) <= now:
                session.delete(record)
                session.commit()
                return None
            principal_id = record.principal_id
            code_verifier = record.code_verifier
            session.delete(record)
            session.commit()
            return principal_id, code_verifier

    def sweep_expired(self) -> None:
        now = _utcnow()
        with self._session_factory() as session:
            session.execute(
                delete(OAuthPendingStateRecord).where(OAuthPendingStateRecord.expires_at <= now)
            )
            session.commit()


def _serialize_payload(payload: dict) -> dict:
    """Serialize a payload dict to be JSON-safe (convert datetime and Principal to storable form)."""
    result = {}
    for key, value in payload.items():
        if isinstance(value, datetime):
            result[key] = {"__datetime__": value.isoformat()}
        elif isinstance(value, Principal):
            result[key] = {"__principal__": value.to_dict()}
        else:
            result[key] = value
    return result


def _deserialize_payload(payload: dict) -> dict:
    """Deserialize a payload dict (convert stored forms back to datetime/Principal)."""
    result = {}
    for key, value in payload.items():
        if isinstance(value, dict) and "__datetime__" in value:
            result[key] = datetime.fromisoformat(value["__datetime__"])
        elif isinstance(value, dict) and "__principal__" in value:
            p = value["__principal__"]
            result[key] = Principal(
                user_id=str(p["user_id"]),
                email=str(p["email"]),
                name=str(p["name"]),
                team_ids=list(p["team_ids"]),
                role=str(p["role"]),
            )
        else:
            result[key] = value
    return result


class RevokedTokenRepository:
    """Tracks revoked JTIs in PostgreSQL with an in-memory cache to minimize DB hits."""

    _CACHE_TTL_SECONDS = 60

    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._cache: dict[str, float] = {}  # jti -> cache expiry (monotonic time)

    def revoke(self, jti: str) -> None:
        record = RevokedTokenRecord(jti=jti, revoked_at=_utcnow())
        with self._session_factory() as session:
            session.merge(record)
            session.commit()
        self._cache[jti] = time.monotonic() + self._CACHE_TTL_SECONDS

    def is_revoked(self, jti: str) -> bool:
        cached_until = self._cache.get(jti)
        if cached_until is not None and time.monotonic() < cached_until:
            return True
        with self._session_factory() as session:
            record = session.get(RevokedTokenRecord, jti)
        if record is not None:
            self._cache[jti] = time.monotonic() + self._CACHE_TTL_SECONDS
            return True
        return False


class _InMemoryRevokedTokenRepository:
    """In-process fallback for tests and no-DB deployments."""

    def __init__(self) -> None:
        self._revoked: set[str] = set()

    def revoke(self, jti: str) -> None:
        self._revoked.add(jti)

    def is_revoked(self, jti: str) -> bool:
        return jti in self._revoked
