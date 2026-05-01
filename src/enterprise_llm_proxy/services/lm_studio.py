from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Iterator

import httpx

from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.domain.credentials import (
    CredentialState,
    CredentialVisibility,
    ProviderCredential,
)
from enterprise_llm_proxy.services.compat_models import build_compat_public_model_id
from enterprise_llm_proxy.services.model_catalog import ModelDefinition

_log = logging.getLogger(__name__)


class LMStudioService:
    def __init__(
        self,
        settings: AppSettings,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client
        if self._settings.lm_studio_enabled and not self._settings.lm_studio_api_key:
            raise ValueError("lm_studio_api_key is required when lm_studio_enabled is true")

    def build_system_credential(self) -> ProviderCredential | None:
        if not self._settings.lm_studio_enabled:
            return None
        discovered_models = [model.upstream_model for model in self.list_models()]
        return ProviderCredential(
            id="cred-system-lmstudio",
            provider="openai_compat",
            auth_kind="api_key",
            account_id=self._settings.lm_studio_account_id,
            provider_alias=self._settings.lm_studio_provider_alias,
            scopes=["chat", "responses", "embeddings"],
            state=CredentialState.ACTIVE,
            expires_at=None,
            cooldown_until=None,
            access_token=json.dumps(
                {
                    "api_key": self._settings.lm_studio_api_key,
                    "base_url": self._normalized_base_url(),
                }
            ),
            refresh_token=None,
            visibility=CredentialVisibility.ENTERPRISE_POOL,
            source="system_lm_studio",
            max_concurrency=self._settings.lm_studio_max_concurrency,
            catalog_info={
                "available_models": discovered_models,
            },
        )

    def list_models(self) -> list[ModelDefinition]:
        if not self._settings.lm_studio_enabled:
            return []
        try:
            payload = self._get_json("/models")
        except Exception:  # pragma: no cover - logged and degraded gracefully
            _log.exception("LM Studio model discovery failed")
            return []

        models: list[ModelDefinition] = []
        seen_ids: set[str] = set()
        for row in payload.get("data", []) if isinstance(payload, dict) else []:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id", "")).strip()
            if not model_id or model_id in seen_ids:
                continue
            seen_ids.add(model_id)
            models.append(
                ModelDefinition(
                    id=build_compat_public_model_id(
                        self._settings.lm_studio_provider_alias,
                        model_id,
                    ),
                    object="model",
                    owned_by="openai_compat",
                    provider="openai_compat",
                    model_profile=model_id,
                    upstream_model=model_id,
                    display_name=model_id,
                    provider_alias=self._settings.lm_studio_provider_alias,
                    supported_protocols=[
                        "openai_chat",
                        "openai_responses",
                        "openai_embeddings",
                    ],
                    supported_clients=["codex"],
                    auth_modes=["api_key"],
                    description=f"{model_id} via LM Studio",
                )
            )
        return models

    def has_model(self, model_id: str) -> bool:
        normalized = str(model_id).strip()
        prefix = f"{self._settings.lm_studio_provider_alias}/"
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
        return any(model.upstream_model == normalized for model in self.list_models())

    def _normalized_base_url(self) -> str:
        return self._settings.lm_studio_base_url.rstrip("/")

    def _get_json(self, path: str) -> dict[str, object]:
        with self._client() as client:
            response = client.get(
                self._url_for(path),
                headers=self._headers(),
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("LM Studio returned a non-object JSON payload")
        return payload

    def _url_for(self, path: str) -> str:
        return f"{self._normalized_base_url()}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        api_key = self._settings.lm_studio_api_key
        if not api_key:
            return {}
        return {
            "Authorization": f"Bearer {api_key}",
            "x-api-key": api_key,
        }

    @contextmanager
    def _client(self) -> Iterator[httpx.Client]:
        if self._http_client is not None:
            yield self._http_client
            return
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            yield client
