from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import jwt
from fastapi import HTTPException, status

from enterprise_llm_proxy.domain.models import Principal


@dataclass(frozen=True)
class OidcIdentity:
    subject: str
    email: str
    name: str
    team_ids: list[str]
    role: str
    avatar_url: str = ""


@dataclass(frozen=True)
class AuthenticatedToken:
    principal: Principal
    kind: str
    claims: dict[str, object]


class OidcClient(Protocol):
    def exchange_code(self, code: str) -> dict[str, str]:
        ...

    def fetch_userinfo(self, access_token: str) -> OidcIdentity:
        ...


class MissingOidcClient:
    def exchange_code(self, code: str) -> dict[str, str]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC client is not configured",
        )

    def fetch_userinfo(self, access_token: str) -> OidcIdentity:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC client is not configured",
        )


class IdentityService:
    def __init__(self, signing_secret: str, oidc_client: OidcClient | None = None) -> None:
        self._signing_secret = signing_secret
        self._oidc_client = oidc_client or MissingOidcClient()

    def authenticate_code(self, code: str) -> Principal:
        token_payload = self._oidc_client.exchange_code(code)
        identity = self._oidc_client.fetch_userinfo(token_payload["access_token"])
        return Principal(
            user_id=identity.subject,
            email=identity.email,
            name=identity.name,
            team_ids=identity.team_ids,
            role=identity.role,
            avatar_url=identity.avatar_url,
        )

    def issue_access_token(self, principal: Principal) -> str:
        return self.issue_token(
            principal,
            kind="human_session",
        )

    def issue_token(
        self,
        principal: Principal,
        *,
        kind: str,
        expires_in_seconds: int | None = None,
        extra_claims: dict[str, object] | None = None,
    ) -> str:
        now = datetime.now(UTC)
        payload: dict[str, object] = {
            **principal.to_dict(),
            "kind": kind,
            "iat": int(now.timestamp()),
            "jti": secrets.token_urlsafe(16),
        }
        if expires_in_seconds is not None:
            payload["exp"] = int((now + timedelta(seconds=expires_in_seconds)).timestamp())
        if extra_claims:
            payload.update(extra_claims)
        return jwt.encode(payload, self._signing_secret, algorithm="HS256")

    def authenticate_token(self, token: str) -> AuthenticatedToken:
        try:
            payload = jwt.decode(token, self._signing_secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token",
            ) from exc

        principal = Principal(
            user_id=payload["user_id"],
            email=payload["email"],
            name=payload["name"],
            team_ids=list(payload["team_ids"]),
            role=payload["role"],
            avatar_url=str(payload.get("avatar_url") or ""),
        )
        return AuthenticatedToken(
            principal=principal,
            kind=str(payload.get("kind", "human_session")),
            claims=dict(payload),
        )

    def authenticate_bearer_token(self, token: str) -> Principal:
        return self.authenticate_token(token).principal
