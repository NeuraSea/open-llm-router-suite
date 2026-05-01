from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import secrets
import socket
import ssl
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


def is_loopback_host(hostname: str) -> bool:
    """Return True if hostname resolves to a loopback address."""
    try:
        infos = socket.getaddrinfo(hostname, None)
        return all(
            ipaddress.ip_address(info[4][0]).is_loopback
            for info in infos
        )
    except OSError:
        return False


def find_caddy_local_ca_cert() -> str | None:
    """Return PEM bundle of all keychain certs on macOS, or None."""
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["security", "find-certificate", "-a", "-p"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


@dataclass(frozen=True)
class RouterctlSession:
    router_base_url: str
    access_token: str
    expires_at: str | None
    principal: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "router_base_url": self.router_base_url,
            "access_token": self.access_token,
            "expires_at": self.expires_at,
            "principal": dict(self.principal),
        }


class RouterctlSessionStore:
    def __init__(self, session_file: Path | None = None) -> None:
        self._session_file = session_file or Path.home() / ".enterprise-llm-proxy" / "session.json"

    @property
    def path(self) -> Path:
        return self._session_file

    def load(self) -> RouterctlSession | None:
        if not self._session_file.exists():
            return None
        payload = json.loads(self._session_file.read_text(encoding="utf-8"))
        return RouterctlSession(
            router_base_url=str(payload["router_base_url"]),
            access_token=str(payload["access_token"]),
            expires_at=payload.get("expires_at") and str(payload["expires_at"]),
            principal=dict(payload["principal"]),
        )

    def save(self, session: RouterctlSession) -> None:
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        self._session_file.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def clear(self) -> None:
        if self._session_file.exists():
            self._session_file.unlink()


class RouterctlApiClient:
    def exchange_bootstrap(
        self,
        *,
        router_base_url: str,
        bootstrap_token: str,
        ca_bundle: str | None = None,
        insecure: bool = False,
    ) -> dict[str, object]:
        response = self._request(
            method="POST",
            url=f"{router_base_url.rstrip('/')}/cli/bootstrap/exchange",
            bearer_token=bootstrap_token,
            verify=self._build_tls_verify(
                router_base_url=router_base_url,
                ca_bundle=ca_bundle,
                insecure=insecure,
            ),
        )
        return dict(response)

    def start_cli_auth(
        self,
        *,
        router_base_url: str,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        ca_bundle: str | None = None,
        insecure: bool = False,
    ) -> dict[str, object]:
        response = self._request(
            method="POST",
            url=f"{router_base_url.rstrip('/')}/cli/auth/start",
            json={
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": code_challenge,
            },
            verify=self._build_tls_verify(
                router_base_url=router_base_url,
                ca_bundle=ca_bundle,
                insecure=insecure,
            ),
        )
        return dict(response)

    def exchange_cli_auth(
        self,
        *,
        router_base_url: str,
        code: str,
        code_verifier: str,
        ca_bundle: str | None = None,
        insecure: bool = False,
    ) -> dict[str, object]:
        response = self._request(
            method="POST",
            url=f"{router_base_url.rstrip('/')}/cli/auth/exchange",
            json={"code": code, "code_verifier": code_verifier},
            verify=self._build_tls_verify(
                router_base_url=router_base_url,
                ca_bundle=ca_bundle,
                insecure=insecure,
            ),
        )
        return dict(response)

    def server_logout(self, *, router_base_url: str, token: str) -> None:
        """Call POST /auth/server-logout to revoke the token server-side.
        Silently ignores network errors — local logout must succeed even if server unreachable."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    f"{router_base_url.rstrip('/')}/auth/server-logout",
                    headers={"Authorization": f"Bearer {token}"},
                )
            resp.raise_for_status()
        except Exception:
            pass  # server unreachable, expired token, etc — local logout still proceeds

    def activate_client(
        self,
        *,
        router_base_url: str,
        cli_session_token: str,
        client: str,
        model: str,
        ca_bundle: str | None = None,
        insecure: bool = False,
    ) -> dict[str, object]:
        response = self._request(
            method="POST",
            url=f"{router_base_url.rstrip('/')}/cli/activate",
            bearer_token=cli_session_token,
            json={"client": client, "model": model},
            verify=self._build_tls_verify(
                router_base_url=router_base_url,
                ca_bundle=ca_bundle,
                insecure=insecure,
            ),
        )
        return dict(response)

    def list_cli_models(
        self,
        *,
        router_base_url: str,
        cli_session_token: str,
        ca_bundle: str | None = None,
        insecure: bool = False,
    ) -> list[dict[str, object]]:
        response = self._request(
            method="GET",
            url=f"{router_base_url.rstrip('/')}/cli/models",
            bearer_token=cli_session_token,
            verify=self._build_tls_verify(
                router_base_url=router_base_url,
                ca_bundle=ca_bundle,
                insecure=insecure,
            ),
        )
        data = response.get("data", [])
        return [dict(item) for item in data if isinstance(item, dict)]

    def get_preferences(
        self,
        *,
        router_base_url: str,
        cli_session_token: str,
        ca_bundle: str | None = None,
        insecure: bool = False,
    ) -> dict[str, object]:
        response = self._request(
            method="GET",
            url=f"{router_base_url.rstrip('/')}/me/preferences",
            bearer_token=cli_session_token,
            verify=self._build_tls_verify(
                router_base_url=router_base_url,
                ca_bundle=ca_bundle,
                insecure=insecure,
            ),
        )
        return dict(response)

    def patch_preferences(
        self,
        *,
        router_base_url: str,
        cli_session_token: str,
        default_model: str | None = None,
        ca_bundle: str | None = None,
        insecure: bool = False,
    ) -> dict[str, object]:
        payload: dict[str, object] = {}
        if default_model is not None:
            payload["default_model"] = default_model
        response = self._request(
            method="PATCH",
            url=f"{router_base_url.rstrip('/')}/me/preferences",
            bearer_token=cli_session_token,
            json=payload,
            verify=self._build_tls_verify(
                router_base_url=router_base_url,
                ca_bundle=ca_bundle,
                insecure=insecure,
            ),
        )
        return dict(response)

    def share_upstream_credential(
        self,
        *,
        router_base_url: str,
        cli_session_token: str,
        credential_id: str,
        ca_bundle: str | None = None,
        insecure: bool = False,
    ) -> dict[str, object]:
        response = self._request(
            method="POST",
            url=f"{router_base_url.rstrip('/')}/me/upstream-credentials/{credential_id}/share",
            bearer_token=cli_session_token,
            verify=self._build_tls_verify(
                router_base_url=router_base_url,
                ca_bundle=ca_bundle,
                insecure=insecure,
            ),
        )
        return dict(response)

    @staticmethod
    def build_pkce_pair() -> tuple[str, str]:
        code_verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
        return code_verifier, code_challenge

    @staticmethod
    def _request(
        *,
        method: str,
        url: str,
        bearer_token: str | None = None,
        json: dict[str, object] | None = None,
        verify: ssl.SSLContext | str | bool = True,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        with httpx.Client(
            timeout=30.0,
            verify=verify,
            trust_env=RouterctlApiClient._should_trust_env(router_base_url=url),
        ) as client:
            response = client.request(method, url, headers=headers, json=json)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", exc.response.text)
            except Exception:
                detail = exc.response.text
            raise httpx.HTTPStatusError(
                f"{exc.response.status_code} {exc.response.reason_phrase}: {detail}",
                request=exc.request,
                response=exc.response,
            ) from None
        return dict(response.json())

    @staticmethod
    def _should_trust_env(*, router_base_url: str) -> bool:
        hostname = urlparse(router_base_url).hostname
        if not hostname:
            return True
        return not is_loopback_host(hostname)

    @staticmethod
    def _build_tls_verify(
        *,
        router_base_url: str,
        ca_bundle: str | None,
        insecure: bool,
    ) -> ssl.SSLContext | str | bool:
        if insecure:
            return False
        if ca_bundle:
            return ca_bundle
        if urlparse(router_base_url).scheme == "https":
            context = ssl.create_default_context()
            hostname = urlparse(router_base_url).hostname or ""
            if is_loopback_host(hostname):
                pem = find_caddy_local_ca_cert()
                if pem:
                    context.load_verify_locations(cadata=pem)
            return context
        return True
