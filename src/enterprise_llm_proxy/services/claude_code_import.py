from __future__ import annotations

import ipaddress
import json
import socket
import ssl
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class ImportedClaudeCredential:
    account_id: str
    access_token: str
    refresh_token: str | None
    scopes: list[str]
    expires_at: str | None   # ISO 8601
    email: str | None
    subscription_type: str | None  # "max", "pro", etc.
    available_models: list[str] | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "account_id": self.account_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "scopes": list(self.scopes),
            "expires_at": self.expires_at,
            "email": self.email,
            "subscription_type": self.subscription_type,
        }
        if self.available_models:
            payload["available_models"] = list(self.available_models)
        return payload


# Service name used by Claude Code CLI when writing to macOS Keychain
_KEYCHAIN_SERVICE = "Claude Code-credentials"
_CLAUDE_JSON = Path.home() / ".claude.json"
_CLAUDE_CODE_CLIENT_VERSION = "2.1.108"


def _read_keychain_entry(service: str) -> dict[str, object]:
    """Read a generic password from the macOS Keychain and return parsed JSON."""
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"CREDENTIAL_NOT_FOUND: 未在 macOS Keychain 中找到 '{service}' 条目。"
            " 请先用 `claude` 命令完成登录，然后再运行此命令。(不可重试)"
        )
    return dict(json.loads(result.stdout.strip()))


def _read_linux_secret(service: str) -> dict[str, object]:
    """Read credential from Linux Secret Service (libsecret) via secret-tool."""
    result = subprocess.run(
        ["secret-tool", "lookup", "service", service],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"CREDENTIAL_NOT_FOUND: 未在 Secret Service 中找到 '{service}' 条目。"
            " 请先用 `claude` 命令完成登录。(不可重试)"
        )
    return dict(json.loads(result.stdout.strip()))


def read_local_claude_credential(
    claude_json_path: Path | None = None,
    keychain_reader: Callable[[str], dict[str, object]] | None = None,
) -> ImportedClaudeCredential:
    """Extract the Claude Code OAuth credential from local storage.

    On macOS: reads from Keychain via `security find-generic-password`.
    On Linux: reads from Secret Service via `secret-tool lookup`.
    """
    if keychain_reader is not None:
        raw = keychain_reader(_KEYCHAIN_SERVICE)
    elif sys.platform == "darwin":
        raw = _read_keychain_entry(_KEYCHAIN_SERVICE)
    elif sys.platform.startswith("linux"):
        raw = _read_linux_secret(_KEYCHAIN_SERVICE)
    else:
        raise RuntimeError(
            "UNSUPPORTED_PLATFORM: 当前平台不支持自动读取 Claude Code 凭证。"
            " 请手动提供 access_token。(不可重试)"
        )

    oauth = raw.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        raise RuntimeError(
            "PARSE_ERROR: Keychain 条目不包含 claudeAiOauth 字段。"
            " 请重新登录 Claude Code 后重试。(可重试)"
        )

    access_token = oauth.get("accessToken")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError(
            "PARSE_ERROR: claudeAiOauth 缺少 accessToken。"
            " 请重新登录 Claude Code 后重试。(可重试)"
        )

    refresh_token = oauth.get("refreshToken")
    scopes = oauth.get("scopes") or []
    subscription_type = oauth.get("subscriptionType")
    expires_at: str | None = None
    raw_expires = oauth.get("expiresAt")
    if isinstance(raw_expires, (int, float)):
        # Claude Code stores expiresAt as Unix milliseconds
        try:
            expires_at = datetime.fromtimestamp(
                raw_expires / 1000.0, tz=timezone.utc
            ).isoformat()
        except (OSError, OverflowError, ValueError):
            expires_at = None
    elif isinstance(raw_expires, str):
        expires_at = raw_expires

    # Account identity from ~/.claude.json
    account_id: str | None = None
    email: str | None = None
    json_path = claude_json_path or _CLAUDE_JSON
    if json_path.exists():
        try:
            claude_data = json.loads(json_path.read_text(encoding="utf-8"))
            acct = claude_data.get("oauthAccount") or {}
            account_id = acct.get("accountUuid") or None
            email = acct.get("emailAddress") or None
        except Exception:
            pass

    if not account_id:
        raise RuntimeError(
            "ACCOUNT_NOT_FOUND: 无法从 ~/.claude.json 读取账号 UUID。"
            " 请确保 Claude Code 已完成登录。(可重试)"
        )

    return ImportedClaudeCredential(
        account_id=account_id,
        access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        scopes=[str(s) for s in scopes if s],
        expires_at=expires_at,
        email=email,
        subscription_type=subscription_type if isinstance(subscription_type, str) else None,
    )


class ClaudeCodeCliImporter:
    def __init__(
        self,
        *,
        credential_reader: Callable[..., ImportedClaudeCredential] | None = None,
        router_uploader: Callable[..., dict[str, object]] | None = None,
        claude_json_path: Path | None = None,
        keychain_reader: Callable[[str], dict[str, object]] | None = None,
        available_models_fetcher: Callable[[str], list[str]] | None = None,
    ) -> None:
        self._credential_reader = credential_reader or read_local_claude_credential
        self._router_uploader = router_uploader or self._upload_to_router
        self._claude_json_path = claude_json_path
        self._keychain_reader = keychain_reader
        self._available_models_fetcher = available_models_fetcher or self._fetch_available_models

    def import_with_cli_session(
        self,
        *,
        router_base_url: str,
        cli_session_token: str,
        ca_bundle: str | None = None,
        insecure: bool = False,
    ) -> dict[str, object]:
        normalized = self._normalize_router_base_url(router_base_url)
        credential = self._credential_reader(
            claude_json_path=self._claude_json_path,
            keychain_reader=self._keychain_reader,
        )
        available_models: list[str] | None = None
        try:
            available_models = self._available_models_fetcher(credential.access_token)
        except Exception:
            available_models = None
        if available_models:
            credential = ImportedClaudeCredential(
                account_id=credential.account_id,
                access_token=credential.access_token,
                refresh_token=credential.refresh_token,
                scopes=credential.scopes,
                expires_at=credential.expires_at,
                email=credential.email,
                subscription_type=credential.subscription_type,
                available_models=available_models,
            )
        return self._router_uploader(
            router_base_url=normalized,
            router_bearer_token=cli_session_token,
            payload=credential.to_payload(),
            verify=self._build_tls_verify(
                router_base_url=normalized,
                ca_bundle=ca_bundle,
                insecure=insecure,
            ),
            trust_env=self._should_trust_env(router_base_url=normalized),
        )

    @staticmethod
    def _normalize_router_base_url(router_base_url: str) -> str:
        normalized = router_base_url.rstrip("/")
        if normalized.endswith("/v1"):
            return normalized[:-3]
        return normalized

    @staticmethod
    def _upload_to_router(
        *,
        router_base_url: str,
        router_bearer_token: str,
        payload: dict[str, object],
        verify: ssl.SSLContext | str | bool = True,
        trust_env: bool = True,
    ) -> dict[str, object]:
        with httpx.Client(timeout=30.0, verify=verify, trust_env=trust_env) as client:
            response = client.post(
                f"{router_base_url}/me/upstream-credentials/claude-max/import",
                headers={"Authorization": f"Bearer {router_bearer_token}"},
                json=payload,
            )
        response.raise_for_status()
        return dict(response.json())

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
            return ClaudeCodeCliImporter._build_system_ssl_context(router_base_url)
        return True

    @staticmethod
    def _should_trust_env(*, router_base_url: str) -> bool:
        hostname = urlparse(router_base_url).hostname
        if not hostname:
            return True
        try:
            addresses = {
                ipaddress.ip_address(sockaddr[0])
                for *_rest, sockaddr in socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
                if sockaddr
            }
        except socket.gaierror:
            return True
        if not addresses:
            return True
        return not all(address.is_loopback for address in addresses)

    @staticmethod
    def _fetch_available_models(access_token: str) -> list[str]:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                "https://api.anthropic.com/v1/models",
                headers=claude_code_oauth_headers(access_token),
            )
        response.raise_for_status()
        payload = response.json()
        return extract_claude_code_available_models(payload)

    @staticmethod
    def _build_system_ssl_context(router_base_url: str) -> ssl.SSLContext:
        del router_base_url
        context = ssl.create_default_context()
        if sys.platform == "darwin":
            result = subprocess.run(
                ["security", "find-certificate", "-a", "-p"],
                capture_output=True,
                check=False,
                text=True,
            )
            if result.returncode == 0 and "BEGIN CERTIFICATE" in result.stdout:
                context.load_verify_locations(cadata=result.stdout.strip())
        return context


def claude_code_oauth_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025-04-20",
        "anthropic-client-name": "claude-code",
        "anthropic-client-version": _CLAUDE_CODE_CLIENT_VERSION,
        "user-agent": f"claude-code/{_CLAUDE_CODE_CLIENT_VERSION}",
    }


def extract_claude_code_available_models(payload: object) -> list[str]:
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    discovered: list[str] = []
    seen: set[str] = set()
    for raw_model in models:
        if not isinstance(raw_model, dict):
            continue
        raw_id = raw_model.get("id")
        if not isinstance(raw_id, str) or not raw_id or raw_id in seen:
            continue
        seen.add(raw_id)
        discovered.append(raw_id)
    return discovered
