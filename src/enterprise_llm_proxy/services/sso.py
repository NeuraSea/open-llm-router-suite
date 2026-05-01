from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt

from enterprise_llm_proxy.domain.models import Principal


@dataclass(frozen=True)
class RouterSsoAssertionSettings:
    issuer: str
    audience: str
    private_key_pem: str | None
    private_key_path: Path | None
    ttl_seconds: int = 60


class RouterSsoAssertionService:
    def __init__(self, settings: RouterSsoAssertionSettings) -> None:
        self._settings = settings

    def issue(self, principal: Principal) -> str:
        key = self._private_key()
        now = datetime.now(UTC)
        ttl = max(1, min(self._settings.ttl_seconds, 60))
        claims: dict[str, object] = {
            "iss": self._settings.issuer,
            "aud": self._settings.audience,
            "sub": principal.user_id,
            "email": principal.email,
            "name": principal.name,
            "role": self._role_claim(principal.role),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        }
        if principal.avatar_url:
            claims["picture"] = principal.avatar_url
            claims["avatar_url"] = principal.avatar_url
        return jwt.encode(claims, key, algorithm="RS256")

    def _private_key(self) -> str:
        if self._settings.private_key_pem:
            return self._settings.private_key_pem.replace("\\n", "\n")
        if self._settings.private_key_path is not None:
            return self._settings.private_key_path.read_text(encoding="utf-8")
        raise RuntimeError("Router SSO private key is not configured")

    @staticmethod
    def _role_claim(role: str) -> str:
        normalized = role.strip().lower()
        if normalized in {"root", "admin"}:
            return normalized
        return "member"
