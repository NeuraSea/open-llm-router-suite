from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator

import httpx


COMPAT_PROVIDERS = {"anthropic_compat", "openai_compat"}
RESERVED_PROVIDER_ALIASES = {
    "anthropic",
    "anthropic_compat",
    "claude-max",
    "deepseek",
    "jina",
    "lmstudio",
    "minimax",
    "openai",
    "openai-codex",
    "openai_compat",
    "qwen",
    "zhipu",
}
PROVIDER_ALIAS_RE = re.compile(r"^[a-z0-9_-]+$")


class CompatModelDiscoveryError(RuntimeError):
    pass


def build_compat_public_model_id(provider_alias: str, upstream_model: str) -> str:
    return f"{provider_alias}/{upstream_model}"


def split_compat_public_model_id(model_name: str) -> tuple[str, str] | None:
    if "/" not in model_name:
        return None
    provider_alias, upstream_model = model_name.split("/", 1)
    if not provider_alias or not upstream_model:
        return None
    return provider_alias, upstream_model


def normalize_provider_alias(raw_alias: object) -> str:
    return str(raw_alias or "").strip().lower()


def validate_provider_alias(provider_alias: str) -> None:
    if not provider_alias:
        raise ValueError("provider_alias is required for compat providers")
    if not PROVIDER_ALIAS_RE.fullmatch(provider_alias):
        raise ValueError("provider_alias must match ^[a-z0-9_-]+$")
    if provider_alias in RESERVED_PROVIDER_ALIASES:
        raise ValueError(f"provider_alias is reserved: {provider_alias}")


def discover_compat_models(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    http_client: httpx.Client | None = None,
) -> list[str]:
    if provider not in COMPAT_PROVIDERS:
        raise ValueError(f"Unsupported compat provider: {provider}")
    normalized_base_url = base_url.strip().rstrip("/")
    if not normalized_base_url:
        raise ValueError("base_url is required for compat providers")
    if not api_key.strip():
        raise ValueError("api_key is required for compat providers")

    with _client(http_client) as client:
        response = client.get(
            f"{normalized_base_url}/models",
            headers=_discovery_headers(provider, api_key),
        )
    if response.status_code >= 400:
        raise CompatModelDiscoveryError(
            f"Compat provider model discovery failed ({response.status_code}): {response.text[:300]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise CompatModelDiscoveryError(
            f"Compat provider model discovery returned non-JSON: {response.text[:300]}"
        ) from exc

    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise CompatModelDiscoveryError("Compat provider model discovery returned invalid payload")

    discovered: list[str] = []
    seen: set[str] = set()
    for raw_model in models:
        if not isinstance(raw_model, dict):
            continue
        model_id = str(raw_model.get("id", "")).strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        discovered.append(model_id)

    if not discovered:
        raise CompatModelDiscoveryError("Compat provider returned zero models")

    return discovered


def _discovery_headers(provider: str, api_key: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "x-api-key": api_key,
    }
    if provider == "anthropic_compat":
        headers["anthropic-version"] = "2023-06-01"
    return headers


@contextmanager
def _client(http_client: httpx.Client | None) -> Iterator[httpx.Client]:
    if http_client is not None:
        yield http_client
        return
    with httpx.Client(timeout=5.0, trust_env=False) as client:
        yield client
