from __future__ import annotations

import json

import httpx
import pytest

from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.domain.credentials import CredentialVisibility
from enterprise_llm_proxy.services.lm_studio import LMStudioService


def test_lm_studio_service_builds_enterprise_pool_credential() -> None:
    service = LMStudioService(
        AppSettings(
            lm_studio_enabled=True,
            lm_studio_api_key="lm-token",
            lm_studio_provider_alias="lmstudio",
        )
    )

    credential = service.build_system_credential()
    token_payload = json.loads(credential.access_token or "{}")

    assert credential.provider == "openai_compat"
    assert credential.auth_kind == "api_key"
    assert credential.account_id == "lm-studio"
    assert credential.provider_alias == "lmstudio"
    assert credential.visibility == CredentialVisibility.ENTERPRISE_POOL
    assert credential.source == "system_lm_studio"
    assert token_payload == {
        "api_key": "lm-token",
        "base_url": "http://host.docker.internal:1234/v1",
    }


def test_lm_studio_service_lists_models_from_openai_compatible_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://lmstudio.local:1234/v1/models")
        assert request.headers["authorization"] == "Bearer lm-token"
        assert request.headers["x-api-key"] == "lm-token"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "zai-org/glm-4.7-flash"},
                    {"id": "openai/gpt-oss-120b"},
                ]
            },
        )

    service = LMStudioService(
        AppSettings(
            lm_studio_enabled=True,
            lm_studio_api_key="lm-token",
            lm_studio_base_url="http://lmstudio.local:1234/v1",
            lm_studio_provider_alias="lmstudio",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    models = service.list_models()

    assert [model.id for model in models] == [
        "lmstudio/zai-org/glm-4.7-flash",
        "lmstudio/openai/gpt-oss-120b",
    ]
    assert models[0].provider == "openai_compat"
    assert models[0].model_profile == "zai-org/glm-4.7-flash"
    assert models[0].upstream_model == "zai-org/glm-4.7-flash"
    assert models[0].supported_protocols == [
        "openai_chat",
        "openai_responses",
        "openai_embeddings",
    ]
    assert models[0].supported_clients == ["codex"]


def test_lm_studio_service_requires_api_key_when_enabled() -> None:
    with pytest.raises(ValueError, match="lm_studio_api_key"):
        LMStudioService(AppSettings(lm_studio_enabled=True))
