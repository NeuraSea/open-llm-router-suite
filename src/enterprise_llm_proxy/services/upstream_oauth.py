from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.domain.models import Principal


@dataclass(frozen=True)
class OAuthFlowStart:
    authorize_url: str
    state: str


@dataclass(frozen=True)
class UpstreamOAuthIdentity:
    subject: str
    email: str
    name: str
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: list[str]


class CodexOAuthBroker(Protocol):
    def start(self, principal: Principal) -> OAuthFlowStart:
        ...

    def finish(
        self,
        *,
        code: str,
        state: str,
        principal: Principal,
    ) -> UpstreamOAuthIdentity:
        ...

    def refresh(self, refresh_token: str | None) -> dict[str, object]:
        ...


@dataclass(frozen=True)
class _PendingAuthorization:
    principal_id: str
    code_verifier: str
    created_at: datetime


class MissingCodexOAuthBroker:
    def start(self, principal: Principal) -> OAuthFlowStart:
        del principal
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Codex OAuth broker is not configured",
        )

    def finish(
        self,
        *,
        code: str,
        state: str,
        principal: Principal,
    ) -> UpstreamOAuthIdentity:
        del code
        del state
        del principal
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Codex OAuth broker is not configured",
        )

    def refresh(self, refresh_token: str | None) -> dict[str, object]:
        del refresh_token
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Codex OAuth broker is not configured",
        )


class OpenAICodexOAuthBroker:
    def __init__(self, settings: AppSettings, oauth_repo: object = None) -> None:
        self._settings = settings
        self._oauth_repo = oauth_repo
        self._pending: dict[str, _PendingAuthorization] = {}

    def start(self, principal: Principal) -> OAuthFlowStart:
        self._assert_configured()
        state = secrets.token_urlsafe(24)
        code_verifier = secrets.token_urlsafe(64)
        if self._oauth_repo is not None:
            expires_at = datetime.now(UTC) + timedelta(minutes=10)
            self._oauth_repo.put_pending(  # type: ignore[attr-defined]
                state=state,
                principal_id=principal.user_id,
                code_verifier=code_verifier,
                expires_at=expires_at,
            )
        else:
            self._pending[state] = _PendingAuthorization(
                principal_id=principal.user_id,
                code_verifier=code_verifier,
                created_at=datetime.now(UTC),
            )
        code_challenge = self._build_code_challenge(code_verifier)
        query = {
            "client_id": self._settings.codex_oauth_client_id,
            "redirect_uri": self._settings.codex_oauth_redirect_uri,
            "response_type": "code",
            "scope": self._settings.codex_oauth_scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if self._settings.codex_oauth_audience:
            query["audience"] = self._settings.codex_oauth_audience
        return OAuthFlowStart(
            authorize_url=f"{self._settings.codex_oauth_authorize_url}?{urlencode(query)}",
            state=state,
        )

    def finish(
        self,
        *,
        code: str,
        state: str,
        principal: Principal,
    ) -> UpstreamOAuthIdentity:
        self._assert_configured()
        if self._oauth_repo is not None:
            result = self._oauth_repo.pop_pending(state)  # type: ignore[attr-defined]
            if result is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired Codex OAuth state",
                )
            pending_principal_id, code_verifier = result
            pending = _PendingAuthorization(
                principal_id=pending_principal_id,
                code_verifier=code_verifier,
                created_at=datetime.now(UTC),
            )
        else:
            pending = self._pending.pop(state, None)
            if pending is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired Codex OAuth state",
                )
        if pending.principal_id != principal.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Codex OAuth state does not match the current session",
            )

        token_payload = self._exchange_code(code, pending.code_verifier)
        access_token = str(token_payload["access_token"])
        userinfo_payload = self._fetch_userinfo(access_token)
        expires_at = self._compute_expires_at(token_payload)
        scopes = self._extract_scopes(token_payload)
        subject = str(
            userinfo_payload.get("sub")
            or userinfo_payload.get("user_id")
            or userinfo_payload.get("id")
            or "openai-user"
        )
        return UpstreamOAuthIdentity(
            subject=subject,
            email=str(userinfo_payload.get("email") or ""),
            name=str(
                userinfo_payload.get("name")
                or userinfo_payload.get("nickname")
                or userinfo_payload.get("preferred_username")
                or subject
            ),
            access_token=access_token,
            refresh_token=token_payload.get("refresh_token")
            and str(token_payload["refresh_token"]),
            expires_at=expires_at,
            scopes=scopes,
        )

    def refresh(self, refresh_token: str | None) -> dict[str, object]:
        self._assert_configured()
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Refresh token is required for Codex OAuth refresh",
            )
        payload = {
            "grant_type": "refresh_token",
            "client_id": self._settings.codex_oauth_client_id,
            "client_secret": self._settings.codex_oauth_client_secret,
            "refresh_token": refresh_token,
        }
        if self._settings.codex_oauth_audience:
            payload["audience"] = self._settings.codex_oauth_audience
        response = self._post_token_request(payload)
        return {
            "access_token": response.get("access_token"),
            "expires_at": self._compute_expires_at(response),
            "state": "active",
        }

    def _exchange_code(self, code: str, code_verifier: str) -> dict[str, object]:
        payload = {
            "grant_type": "authorization_code",
            "client_id": self._settings.codex_oauth_client_id,
            "client_secret": self._settings.codex_oauth_client_secret,
            "code": code,
            "redirect_uri": self._settings.codex_oauth_redirect_uri,
            "code_verifier": code_verifier,
        }
        if self._settings.codex_oauth_audience:
            payload["audience"] = self._settings.codex_oauth_audience
        return self._post_token_request(payload)

    def _post_token_request(self, payload: dict[str, object]) -> dict[str, object]:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                self._settings.codex_oauth_token_url,
                json=payload,
            )
        if response.status_code >= 400:
            detail = response.text or "Codex OAuth token exchange failed"
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=detail[:512],
            )
        return dict(response.json())

    def _fetch_userinfo(self, access_token: str) -> dict[str, object]:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                self._settings.codex_oauth_userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Codex OAuth userinfo request failed",
            )
        return dict(response.json())

    def _assert_configured(self) -> None:
        if not (
            self._settings.codex_oauth_client_id
            and self._settings.codex_oauth_client_secret
            and self._settings.codex_oauth_redirect_uri
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Codex OAuth broker is not configured",
            )

    @staticmethod
    def _extract_scopes(payload: dict[str, object]) -> list[str]:
        scope_value = payload.get("scope")
        if isinstance(scope_value, str) and scope_value:
            return [part for part in scope_value.split() if part]
        return []

    @staticmethod
    def _compute_expires_at(payload: dict[str, object]) -> datetime | None:
        expires_in = payload.get("expires_in")
        if isinstance(expires_in, int):
            return datetime.now(UTC) + timedelta(seconds=expires_in)
        if isinstance(expires_in, float):
            return datetime.now(UTC) + timedelta(seconds=int(expires_in))
        return None

    @staticmethod
    def _build_code_challenge(code_verifier: str) -> str:
        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


class CodexOAuthCredentialRefresher:
    def __init__(
        self,
        broker: CodexOAuthBroker,
        fallback: object | None = None,
    ) -> None:
        self._broker = broker
        self._fallback = fallback

    def refresh(self, provider: str, refresh_token: str | None) -> dict[str, object]:
        if provider == "openai-codex" and refresh_token:
            return self._broker.refresh(refresh_token)
        if self._fallback is not None:
            return self._fallback.refresh(provider, refresh_token)  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Credential refresher is not configured for {provider}",
        )
