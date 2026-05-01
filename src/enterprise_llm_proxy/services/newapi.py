from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.domain.credentials import CredentialState, CredentialVisibility, ProviderCredential
from enterprise_llm_proxy.domain.models import Principal

_NATIVE_API_KEY_CHANNELS: dict[str, tuple[int, str, str]] = {
    "zhipu": (26, "router-zhipu", "https://open.bigmodel.cn"),
    "deepseek": (43, "router-deepseek", "https://api.deepseek.com"),
    "minimax": (35, "router-minimax", "https://api.minimax.chat"),
    "jina": (38, "router-jina", "https://api.jina.ai"),
}

NATIVE_API_KEY_PROVIDER_DEFAULT_MODELS: dict[str, list[str]] = {
    "jina": [
        "jina-embeddings-v4",
        "jina-embeddings-v3",
        "jina-reranker-v3",
        "jina-reranker-m0",
        "jina-reranker-v2-base-multilingual",
        "jina-colbert-v2",
    ],
}


class NewApiClient(Protocol):
    def add_channel(self, payload: dict[str, object]) -> dict[str, object]:
        ...

    def update_channel(self, payload: dict[str, object]) -> dict[str, object]:
        ...

    def find_channel_by_name(self, name: str) -> dict[str, object] | None:
        ...


class HttpNewApiAdminClient:
    def __init__(self, *, base_url: str, admin_access_token: str, admin_user_id: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_access_token = admin_access_token
        self._admin_user_id = admin_user_id

    def add_channel(self, payload: dict[str, object]) -> dict[str, object]:
        return self._request("POST", "/api/channel/", payload)

    def update_channel(self, payload: dict[str, object]) -> dict[str, object]:
        return self._request("PUT", "/api/channel/", payload)

    def find_channel_by_name(self, name: str) -> dict[str, object] | None:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self._base_url}/api/channel/search",
                headers={
                    "Authorization": self._admin_access_token,
                    "New-Api-User": self._admin_user_id,
                },
                params={"keyword": name, "page_size": 50},
            )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            return None
        data = body.get("data")
        if not isinstance(data, dict):
            return None
        items = data.get("items")
        if not isinstance(items, list):
            return None
        for item in items:
            if isinstance(item, dict) and item.get("name") == name:
                return dict(item)
        return None

    def _request(self, method: str, path: str, payload: dict[str, object]) -> dict[str, object]:
        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method,
                f"{self._base_url}{path}",
                headers={
                    "Authorization": self._admin_access_token,
                    "New-Api-User": self._admin_user_id,
                },
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        return dict(body) if isinstance(body, dict) else {"data": body}


@dataclass(frozen=True)
class NewApiSyncResult:
    enabled: bool
    action: str
    group: str | None = None
    response: dict[str, object] | None = None


class NewApiCredentialSyncService:
    def __init__(
        self,
        *,
        settings: AppSettings,
        client: NewApiClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or self._build_client(settings)

    def sync_credential(
        self,
        credential: ProviderCredential,
        principal: Principal,
        *,
        shared: bool | None = None,
    ) -> NewApiSyncResult:
        if not self._settings.newapi_sync_enabled or self._client is None:
            return NewApiSyncResult(enabled=False, action="skipped")
        if credential.state != CredentialState.ACTIVE:
            return NewApiSyncResult(enabled=False, action="skipped_inactive")

        channel = self._channel_for_credential(
            credential,
            principal,
            shared=shared if shared is not None else credential.visibility == CredentialVisibility.ENTERPRISE_POOL,
        )
        if channel is None:
            return NewApiSyncResult(enabled=False, action="unsupported")

        find_channel = getattr(self._client, "find_channel_by_name", None)
        existing = (
            find_channel(str(channel["name"]))
            if callable(find_channel)
            else None
        )
        if existing is not None and existing.get("id") is not None:
            channel["id"] = existing["id"]
            response = self._client.update_channel(channel)
            action = "update_channel"
        else:
            response = self._client.add_channel({"mode": "single", "channel": channel})
            action = "create_channel"
        return NewApiSyncResult(
            enabled=True,
            action=action,
            group=str(channel["group"]),
            response=response,
        )

    def _channel_for_credential(
        self,
        credential: ProviderCredential,
        principal: Principal,
        *,
        shared: bool,
    ) -> dict[str, object] | None:
        group = build_newapi_group(
            principal=principal,
            enterprise_group=self._settings.newapi_enterprise_group,
            shared=shared,
        )
        if credential.provider == "openai-codex":
            return self._codex_channel(credential, principal=principal, group=group)
        if credential.provider == "claude-max":
            return self._claude_bridge_channel(credential, principal=principal, group=group)
        if credential.provider == "openai_compat":
            return self._openai_compat_channel(credential, principal=principal, group=group)
        if credential.provider in _NATIVE_API_KEY_CHANNELS:
            return self._native_api_key_channel(credential, principal=principal, group=group)
        return None

    def _codex_channel(
        self,
        credential: ProviderCredential,
        *,
        principal: Principal,
        group: str,
    ) -> dict[str, object]:
        if not self._settings.bridge_base_url_for_newapi:
            raise RuntimeError("bridge_base_url_for_newapi is required for Codex sync")
        if not self._settings.bridge_upstream_api_key:
            raise RuntimeError("bridge_upstream_api_key is required for Codex sync")

        models = _available_models(credential) or [
            "gpt-5",
            "gpt-5-codex",
            "gpt-5.1-codex",
            "gpt-5.3-codex",
            "gpt-5.3-codex-spark",
            "gpt-5.4",
        ]
        base_url = (
            self._settings.bridge_base_url_for_newapi.rstrip("/")
            + f"/bridge/upstreams/credentials/{credential.id}/openai"
        )
        return {
            "type": 1,
            "key": self._settings.bridge_upstream_api_key,
            "name": _channel_name("router-codex", principal, credential),
            "base_url": base_url,
            "models": ",".join(models),
            "group": group,
            "status": 1,
            "tag": "router-oauth-bridge",
            "auto_ban": 0,
        }

    def _claude_bridge_channel(
        self,
        credential: ProviderCredential,
        *,
        principal: Principal,
        group: str,
    ) -> dict[str, object]:
        if not self._settings.bridge_base_url_for_newapi:
            raise RuntimeError("bridge_base_url_for_newapi is required for Claude Max sync")
        if not self._settings.bridge_upstream_api_key:
            raise RuntimeError("bridge_upstream_api_key is required for Claude Max sync")

        base_url = (
            self._settings.bridge_base_url_for_newapi.rstrip("/")
            + f"/bridge/upstreams/credentials/{credential.id}/anthropic"
        )
        models = _available_models(credential) or [
            "claude-sonnet-4-6",
            "claude-opus-4-6",
        ]
        return {
            "type": 14,
            "key": self._settings.bridge_upstream_api_key,
            "name": _channel_name("router-claude-max", principal, credential),
            "base_url": base_url,
            "models": ",".join(models),
            "group": group,
            "status": 1,
            "tag": "router-oauth",
            "auto_ban": 0,
        }

    def _openai_compat_channel(
        self,
        credential: ProviderCredential,
        *,
        principal: Principal,
        group: str,
    ) -> dict[str, object]:
        provider_alias = (credential.provider_alias or "").strip()
        if not provider_alias:
            raise RuntimeError("provider_alias is required for OpenAI-compatible New API sync")
        compat_key = _parse_compat_key(credential)
        upstream_models = _available_models(credential)
        models, model_mapping = _mapped_models(provider_alias, upstream_models)
        return {
            "type": 1,
            "key": compat_key["api_key"],
            "name": _channel_name(f"router-{provider_alias}", principal, credential),
            "base_url": _strip_openai_v1_suffix(compat_key["base_url"]),
            "models": ",".join(models),
            "model_mapping": json.dumps(model_mapping, ensure_ascii=False, separators=(",", ":")),
            "group": group,
            "status": 1,
            "tag": "router-compat",
            "auto_ban": 0,
        }

    def _native_api_key_channel(
        self,
        credential: ProviderCredential,
        *,
        principal: Principal,
        group: str,
    ) -> dict[str, object]:
        channel_type, name_prefix, base_url = _NATIVE_API_KEY_CHANNELS[credential.provider]
        upstream_models = _available_models(credential) or _default_provider_models(credential.provider)
        models, model_mapping = _mapped_models(credential.provider, upstream_models)
        return {
            "type": channel_type,
            "key": credential.access_token or "",
            "name": _channel_name(name_prefix, principal, credential),
            "base_url": base_url,
            "models": ",".join(models),
            "model_mapping": json.dumps(model_mapping, ensure_ascii=False, separators=(",", ":")),
            "group": group,
            "status": 1,
            "tag": "router-byok",
            "auto_ban": 0,
        }

    @staticmethod
    def _build_client(settings: AppSettings) -> NewApiClient | None:
        if not (
            settings.newapi_base_url
            and settings.newapi_admin_access_token
            and settings.newapi_admin_user_id
        ):
            return None
        return HttpNewApiAdminClient(
            base_url=settings.newapi_base_url,
            admin_access_token=settings.newapi_admin_access_token,
            admin_user_id=settings.newapi_admin_user_id,
        )


def build_newapi_group(
    *,
    principal: Principal,
    enterprise_group: str,
    shared: bool,
) -> str:
    private_group = f"private-{_safe_group_fragment(principal.user_id)}"
    if not shared:
        return private_group
    enterprise = enterprise_group.strip() or "default"
    if enterprise == private_group:
        return private_group
    return f"{private_group},{enterprise}"


def _safe_group_fragment(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-")
    return normalized[:48] or "user"


def _available_models(credential: ProviderCredential) -> list[str]:
    raw = None
    if isinstance(credential.catalog_info, dict):
        raw = credential.catalog_info.get("available_models")
    if not isinstance(raw, list) and isinstance(credential.quota_info, dict):
        raw = credential.quota_info.get("available_models")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        model = str(item).strip()
        if model and model not in seen:
            seen.add(model)
            out.append(model)
    return out


def _parse_compat_key(credential: ProviderCredential) -> dict[str, str]:
    try:
        parsed = json.loads(credential.access_token or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI-compatible credential access_token is not valid JSON") from exc
    api_key = str(parsed.get("api_key", "")).strip()
    base_url = str(parsed.get("base_url", "")).strip()
    if not api_key:
        raise RuntimeError("OpenAI-compatible credential is missing api_key")
    if not base_url:
        raise RuntimeError("OpenAI-compatible credential is missing base_url")
    return {"api_key": api_key, "base_url": base_url}


def _strip_openai_v1_suffix(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[:-3]
    return normalized


def _mapped_models(provider: str, upstream_models: list[str]) -> tuple[list[str], dict[str, str]]:
    models: list[str] = []
    mapping: dict[str, str] = {}
    seen: set[str] = set()
    for upstream_model in upstream_models:
        model = upstream_model.strip()
        if not model:
            continue
        public_model = f"{provider}/{model}"
        if public_model in seen:
            continue
        seen.add(public_model)
        models.append(public_model)
        mapping[public_model] = model
    return models, mapping


def _default_provider_models(provider: str) -> list[str]:
    if provider in NATIVE_API_KEY_PROVIDER_DEFAULT_MODELS:
        return list(NATIVE_API_KEY_PROVIDER_DEFAULT_MODELS[provider])
    try:
        from enterprise_llm_proxy.services import provider_registry
    except Exception:
        return []
    return [model.upstream_model for model in provider_registry.get_provider_models(provider)]


def _channel_name(prefix: str, principal: Principal, credential: ProviderCredential) -> str:
    return f"{prefix}-{_safe_group_fragment(principal.user_id)}-{_safe_group_fragment(credential.account_id)}"


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
