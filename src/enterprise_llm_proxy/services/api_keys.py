from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException, status

from enterprise_llm_proxy.domain.models import Principal


@dataclass(frozen=True)
class PlatformApiKey:
    id: str
    principal: Principal
    name: str
    key_prefix: str
    key_hash: str
    created_at: datetime

    def to_public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "principal_id": self.principal.user_id,
            "name": self.name,
            "key_prefix": self.key_prefix,
            "created_at": self.created_at.isoformat(),
        }


class PlatformApiKeyService:
    def __init__(self, repository=None) -> None:  # type: ignore[no-untyped-def]
        self._repository = repository
        self._keys_by_hash: dict[str, PlatformApiKey] = {}

    def create_key(self, *, principal: Principal, name: str) -> tuple[PlatformApiKey, str]:
        secret = f"elp_{secrets.token_urlsafe(24)}"
        key_hash = self._hash(secret)
        record = PlatformApiKey(
            id=f"key_{uuid4().hex}",
            principal=principal,
            name=name,
            key_prefix=secret[:12],
            key_hash=key_hash,
            created_at=datetime.now(UTC),
        )
        if self._repository is not None:
            self._repository.save(record)
        else:
            self._keys_by_hash[key_hash] = record
        return record, secret

    def list_for_user(self, user_id: str) -> list[PlatformApiKey]:
        """List all API keys for a user."""
        if self._repository is not None:
            return self._repository.list_for_principal(user_id)
        return [key for key in self._keys_by_hash.values() if key.principal.user_id == user_id]

    def delete_key(self, key_id: str, user_id: str) -> bool:
        """Delete a key owned by user. Returns True if found and deleted, False if not found."""
        if self._repository is not None:
            return self._repository.delete(key_id, user_id)
        for key_hash, key in list(self._keys_by_hash.items()):
            if key.id == key_id and key.principal.user_id == user_id:
                del self._keys_by_hash[key_hash]
                return True
        return False

    def authenticate(self, api_key: str) -> Principal:
        key_hash = self._hash(api_key)
        record = (
            self._repository.find_by_hash(key_hash)
            if self._repository is not None
            else self._keys_by_hash.get(key_hash)
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token",
            )
        return record.principal

    @staticmethod
    def _hash(api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
