from __future__ import annotations

import base64
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx


CommandRunner = Callable[[list[str]], None]


@dataclass(frozen=True)
class ImportedCodexCredential:
    account_id: str
    access_token: str
    refresh_token: str | None
    scopes: list[str]
    expires_at: str | None
    subject: str | None
    email: str | None
    available_models: list[str] | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "account_id": self.account_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "scopes": list(self.scopes),
            "expires_at": self.expires_at,
            "subject": self.subject,
            "email": self.email,
        }
        if self.available_models:
            payload["available_models"] = list(self.available_models)
        return payload


class CodexCliImporter:
    def __init__(
        self,
        *,
        command_runner: Callable[[list[str], dict[str, str]], None] | None = None,
        router_uploader: Callable[..., dict[str, object]] | None = None,
        temp_root: Path | None = None,
        codex_bin: str = "codex",
    ) -> None:
        self._command_runner = command_runner or self._run_command
        self._router_uploader = router_uploader or self._upload_to_router
        self._temp_root = temp_root
        self._codex_bin = codex_bin

    def import_credential(
        self,
        *,
        router_base_url: str,
        router_api_key: str,
        ca_bundle: str | None = None,
        insecure: bool = False,
    ) -> dict[str, object]:
        normalized_router_base_url = self._normalize_router_base_url(router_base_url)
        temp_home = Path(
            tempfile.mkdtemp(prefix="router-codex-import-", dir=str(self._temp_root) if self._temp_root else None)
        )
        try:
            self._write_config(temp_home)
            env = dict(os.environ)
            env["CODEX_HOME"] = str(temp_home)

            try:
                self._command_runner([self._codex_bin, "login"], env=env)
            except subprocess.CalledProcessError:
                self._command_runner([self._codex_bin, "login", "--device-auth"], env=env)

            credential = self._read_auth_file(
                temp_home / "auth.json",
                available_models=self._read_models_cache_with_fallback(temp_home),
            )
            return self._router_uploader(
                router_base_url=normalized_router_base_url,
                router_api_key=router_api_key,
                payload=credential.to_payload(),
                verify=self._build_tls_verify(router_base_url=normalized_router_base_url, ca_bundle=ca_bundle, insecure=insecure),
                trust_env=self._should_trust_env(router_base_url=normalized_router_base_url),
            )
        finally:
            shutil.rmtree(temp_home, ignore_errors=True)

    def import_with_cli_session(
        self,
        *,
        router_base_url: str,
        cli_session_token: str,
        ca_bundle: str | None = None,
        insecure: bool = False,
    ) -> dict[str, object]:
        normalized_router_base_url = self._normalize_router_base_url(router_base_url)
        temp_home = Path(
            tempfile.mkdtemp(prefix="router-codex-import-", dir=str(self._temp_root) if self._temp_root else None)
        )
        try:
            self._write_config(temp_home)
            env = dict(os.environ)
            env["CODEX_HOME"] = str(temp_home)

            try:
                self._command_runner([self._codex_bin, "login"], env=env)
            except subprocess.CalledProcessError:
                self._command_runner([self._codex_bin, "login", "--device-auth"], env=env)

            credential = self._read_auth_file(
                temp_home / "auth.json",
                available_models=self._read_models_cache_with_fallback(temp_home),
            )
            return self._router_uploader(
                router_base_url=normalized_router_base_url,
                router_bearer_token=cli_session_token,
                payload=credential.to_payload(),
                verify=self._build_tls_verify(
                    router_base_url=normalized_router_base_url,
                    ca_bundle=ca_bundle,
                    insecure=insecure,
                ),
                trust_env=self._should_trust_env(router_base_url=normalized_router_base_url),
            )
        finally:
            shutil.rmtree(temp_home, ignore_errors=True)

    def _write_config(self, temp_home: Path) -> None:
        temp_home.mkdir(parents=True, exist_ok=True)
        (temp_home / "config.toml").write_text(
            'cli_auth_credentials_store = "file"\n',
            encoding="utf-8",
        )

    def _read_auth_file(
        self,
        path: Path,
        *,
        available_models: list[str] | None = None,
    ) -> ImportedCodexCredential:
        payload = json.loads(path.read_text(encoding="utf-8"))
        auth_mode = payload.get("auth_mode")
        if auth_mode != "chatgpt":
            raise ValueError("Codex import only supports chatgpt auth_mode")

        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            raise ValueError("Codex auth.json is missing tokens")

        access_token = tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Codex auth.json is missing access_token")

        refresh_token = tokens.get("refresh_token")
        id_token = tokens.get("id_token")
        claims = self._decode_id_token(id_token) if isinstance(id_token, str) and id_token else {}
        subject = claims.get("sub") if isinstance(claims.get("sub"), str) else None
        email = claims.get("email") if isinstance(claims.get("email"), str) else None
        account_id = tokens.get("account_id")
        if not isinstance(account_id, str) or not account_id:
            account_id = subject
        if not account_id:
            raise ValueError("Codex auth.json is missing account_id")

        scopes = ["openid", "profile"]
        if email:
            scopes.append("email")
        if isinstance(refresh_token, str) and refresh_token:
            scopes.append("offline_access")

        expires_at = None
        exp = claims.get("exp")
        if isinstance(exp, int):
            expires_at = datetime.fromtimestamp(exp, tz=UTC).isoformat()

        return ImportedCodexCredential(
            account_id=account_id,
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            scopes=scopes,
            expires_at=expires_at,
            subject=subject,
            email=email,
            available_models=available_models or None,
        )

    @staticmethod
    def _read_models_cache(path: Path) -> list[str]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        models = payload.get("models")
        if not isinstance(models, list):
            return []
        discovered: list[str] = []
        seen: set[str] = set()
        for raw_model in models:
            if not isinstance(raw_model, dict):
                continue
            slug = raw_model.get("slug")
            visibility = raw_model.get("visibility")
            if not isinstance(slug, str) or not slug or slug in seen:
                continue
            if visibility != "list":
                continue
            seen.add(slug)
            discovered.append(slug)
        return discovered

    def _read_models_cache_with_fallback(self, temp_home: Path) -> list[str]:
        temp_models = self._read_models_cache(temp_home / "models_cache.json")
        if temp_models:
            return temp_models
        return self._read_models_cache(Path.home() / ".codex" / "models_cache.json")

    @staticmethod
    def _decode_id_token(id_token: str) -> dict[str, object]:
        parts = id_token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + ("=" * (-len(parts[1]) % 4))
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8"))
        return dict(json.loads(decoded))

    @staticmethod
    def _run_command(command: list[str], *, env: dict[str, str]) -> None:
        subprocess.run(command, env=env, check=True)

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
        router_api_key: str | None = None,
        router_bearer_token: str | None = None,
        payload: dict[str, object],
        verify: ssl.SSLContext | str | bool = True,
        trust_env: bool = True,
    ) -> dict[str, object]:
        bearer_token = router_bearer_token or router_api_key
        if not bearer_token:
            raise ValueError("A router bearer token is required")
        with httpx.Client(timeout=30.0, verify=verify, trust_env=trust_env) as client:
            response = client.post(
                f"{router_base_url}/me/upstream-credentials/codex/import",
                headers={"Authorization": f"Bearer {bearer_token}"},
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
            return CodexCliImporter._build_system_ssl_context(router_base_url)
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
    def _build_system_ssl_context(router_base_url: str) -> ssl.SSLContext:
        context = ssl.create_default_context()
        if sys.platform == "darwin":
            local_ca_pem = CodexCliImporter._read_darwin_local_ca_pem()
            if local_ca_pem:
                context.load_verify_locations(cadata=local_ca_pem)
        return context

    @staticmethod
    def _read_darwin_local_ca_pem() -> str | None:
        result = subprocess.run(
            ["security", "find-certificate", "-a", "-p"],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            return None
        pem_bundle = result.stdout.strip()
        if "BEGIN CERTIFICATE" not in pem_bundle:
            return None
        return pem_bundle
