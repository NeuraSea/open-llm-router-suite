from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.services.identity import OidcIdentity


class FeishuOidcClient:
    def __init__(
        self,
        *,
        settings: AppSettings,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client or httpx.Client(timeout=10.0, trust_env=False)

    def exchange_code(self, code: str) -> dict[str, str]:
        if not self._settings.feishu_token_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Feishu OIDC token URL is not configured",
            )

        response = self._http_client.post(
            self._settings.feishu_token_url,
            json={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self._settings.feishu_client_id,
                "client_secret": self._settings.feishu_client_secret,
                "redirect_uri": self._settings.feishu_redirect_uri,
            },
        )
        response.raise_for_status()
        payload = response.json()
        access_token = payload.get("access_token") or payload.get("data", {}).get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Feishu token exchange did not return access_token",
            )
        return {"access_token": str(access_token)}

    def fetch_userinfo(self, access_token: str) -> OidcIdentity:
        if not self._settings.feishu_userinfo_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Feishu OIDC userinfo URL is not configured",
            )

        response = self._http_client.get(
            self._settings.feishu_userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", payload)
        logger.info("Feishu userinfo fields: %s", list(data.keys()))
        subject = str(data.get("open_id") or data.get("union_id") or data.get("user_id"))
        email = data.get("email") or data.get("enterprise_email") or ""
        team_ids = list(data.get("department_ids") or data.get("department_id_list") or [])
        if not team_ids:
            team_ids = ["default"]
        is_admin = email in self._settings.admin_emails or subject in self._settings.admin_subjects

        return OidcIdentity(
            subject=subject,
            email=str(email),
            name=str(data.get("name") or data.get("en_name") or email or "Feishu User"),
            team_ids=[str(team_id) for team_id in team_ids],
            role="admin" if is_admin else "member",
            avatar_url=str(data.get("avatar_url") or data.get("avatar_thumb") or ""),
        )
