from __future__ import annotations

import httpx
from fastapi import HTTPException, status

from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.services.identity import OidcIdentity


class GenericOidcClient:
    def __init__(
        self,
        *,
        settings: AppSettings,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client or httpx.Client(timeout=10.0, trust_env=False)

    def exchange_code(self, code: str) -> dict[str, str]:
        if not self._settings.oidc_token_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC token URL is not configured",
            )

        response = self._http_client.post(
            self._settings.oidc_token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self._settings.oidc_client_id or "",
                "client_secret": self._settings.oidc_client_secret or "",
                "redirect_uri": self._settings.oidc_redirect_uri or "",
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        access_token = payload.get("access_token") or payload.get("data", {}).get(
            "access_token"
        )
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OIDC token exchange did not return access_token",
            )
        return {"access_token": str(access_token)}

    def fetch_userinfo(self, access_token: str) -> OidcIdentity:
        if not self._settings.oidc_userinfo_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC userinfo URL is not configured",
            )

        response = self._http_client.get(
            self._settings.oidc_userinfo_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
            },
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", payload)
        subject = str(
            data.get("sub")
            or data.get("user_id")
            or data.get("id")
            or data.get("open_id")
            or data.get("union_id")
            or ""
        )
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OIDC userinfo did not return subject",
            )

        email = str(data.get("email") or data.get("enterprise_email") or "")
        name = str(
            data.get("name")
            or data.get("display_name")
            or data.get("login")
            or email
            or subject
        )
        avatar_url = str(
            data.get("picture")
            or data.get("avatar_url")
            or data.get("avatar")
            or data.get("photo_url")
            or ""
        )
        raw_groups = (
            data.get("groups")
            or data.get("group_ids")
            or data.get("department_ids")
            or data.get("department_id_list")
            or ["default"]
        )
        if isinstance(raw_groups, str):
            team_ids = [raw_groups]
        else:
            team_ids = [str(group) for group in raw_groups]
        if not team_ids:
            team_ids = ["default"]

        claim_role = str(data.get("role") or "").lower()
        claim_admin = bool(data.get("admin") or data.get("is_admin"))
        is_admin = (
            email in self._settings.admin_emails
            or subject in self._settings.admin_subjects
            or (
                self._settings.oidc_trust_admin_claim
                and (claim_admin or claim_role in {"admin", "root"})
            )
        )

        return OidcIdentity(
            subject=subject,
            email=email,
            name=name,
            team_ids=team_ids,
            role="admin" if is_admin else "member",
            avatar_url=avatar_url,
        )
