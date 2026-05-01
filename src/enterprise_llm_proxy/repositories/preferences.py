from __future__ import annotations
from datetime import UTC, datetime
from dataclasses import dataclass
from typing import Protocol


@dataclass
class UserPreferences:
    user_id: str
    default_model: str | None
    routing_config: dict

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "default_model": self.default_model,
            "routing_config": self.routing_config,
        }


class UserPreferencesRepository(Protocol):
    def get(self, user_id: str) -> UserPreferences | None: ...
    def upsert(self, user_id: str, default_model: str | None, routing_config: dict | None) -> UserPreferences: ...


class InMemoryUserPreferencesRepository:
    def __init__(self) -> None:
        self._store: dict[str, UserPreferences] = {}

    def get(self, user_id: str) -> UserPreferences | None:
        return self._store.get(user_id)

    def upsert(self, user_id: str, default_model: str | None, routing_config: dict | None) -> UserPreferences:
        existing = self._store.get(user_id) or UserPreferences(user_id=user_id, default_model=None, routing_config={})
        updated = UserPreferences(
            user_id=user_id,
            default_model=default_model if default_model is not None else existing.default_model,
            routing_config=routing_config if routing_config is not None else existing.routing_config,
        )
        self._store[user_id] = updated
        return updated


class PostgresUserPreferencesRepository:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def get(self, user_id: str) -> UserPreferences | None:
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError, ProgrammingError
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text("SELECT user_id, default_model, routing_config FROM user_preferences WHERE user_id = :uid"),
                    {"uid": user_id},
                ).fetchone()
                if row is None:
                    return None
                return UserPreferences(user_id=row.user_id, default_model=row.default_model, routing_config=row.routing_config or {})
        except (ProgrammingError, OperationalError):
            # Table not yet created or DB unreachable — degrade gracefully
            return None

    def upsert(self, user_id: str, default_model: str | None, routing_config: dict | None) -> UserPreferences:
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError, ProgrammingError
        import json
        now = datetime.now(UTC)
        try:
            with self._session_factory() as session:
                existing_row = session.execute(
                    text("SELECT user_id, default_model, routing_config FROM user_preferences WHERE user_id = :uid"),
                    {"uid": user_id},
                ).fetchone()
                if existing_row is None:
                    new_dm = default_model
                    new_rc = routing_config or {}
                else:
                    new_dm = default_model if default_model is not None else existing_row.default_model
                    new_rc = routing_config if routing_config is not None else (existing_row.routing_config or {})
                session.execute(
                    text("""
                        INSERT INTO user_preferences (user_id, default_model, routing_config, updated_at)
                        VALUES (:uid, :dm, :rc::jsonb, :ts)
                        ON CONFLICT (user_id) DO UPDATE
                        SET default_model = EXCLUDED.default_model,
                            routing_config = EXCLUDED.routing_config,
                            updated_at = EXCLUDED.updated_at
                    """),
                    {"uid": user_id, "dm": new_dm, "rc": json.dumps(new_rc), "ts": now},
                )
                session.commit()
                return UserPreferences(user_id=user_id, default_model=new_dm, routing_config=new_rc)
        except (ProgrammingError, OperationalError):
            return UserPreferences(user_id=user_id, default_model=default_model, routing_config=routing_config or {})
