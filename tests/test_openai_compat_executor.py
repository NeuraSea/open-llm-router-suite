from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from enterprise_llm_proxy.domain.credentials import (
    CredentialState,
    CredentialVisibility,
    ProviderCredential,
)
from enterprise_llm_proxy.domain.inference import UnifiedInferenceRequest
from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.services.openai_compat_executor import OpenAICompatExecutor
from enterprise_llm_proxy.services.execution import UpstreamCredentialInvalidError


def _make_credential() -> ProviderCredential:
    return ProviderCredential(
        id="cred-compat",
        provider="openai_compat",
        auth_kind="api_key",
        account_id="lm-studio",
        scopes=["chat", "responses"],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token=json.dumps(
            {
                "api_key": "lm-token",
                "base_url": "http://lmstudio.local:1234/v1",
            }
        ),
        refresh_token=None,
        visibility=CredentialVisibility.ENTERPRISE_POOL,
        source="system_lm_studio",
        max_concurrency=1,
    )


def _make_principal() -> Principal:
    return Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )


def test_openai_compat_executor_posts_chat_completions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://lmstudio.local:1234/v1/chat/completions")
        assert request.headers["authorization"] == "Bearer lm-token"
        assert request.headers["x-api-key"] == "lm-token"
        assert json.loads(request.read()) == {
            "model": "zai-org/glm-4.7-flash",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 32,
        }
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-123",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "hello"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
        )

    executor = OpenAICompatExecutor(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    request = UnifiedInferenceRequest(
        request_id="req-chat",
        protocol="openai_chat",
        model="zai-org/glm-4.7-flash",
        model_profile="zai-org/glm-4.7-flash",
        upstream_model="zai-org/glm-4.7-flash",
        auth_modes=["api_key"],
        provider="openai_compat",
        payload={
            "model": "ignored-by-router",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 32,
        },
        principal=_make_principal(),
        estimated_units=32,
    )

    result = executor.execute(request, _make_credential())

    assert result.body["id"] == "chatcmpl-123"
    assert result.tokens_in == 11
    assert result.tokens_out == 7


def test_openai_compat_executor_posts_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://lmstudio.local:1234/v1/responses")
        assert request.headers["authorization"] == "Bearer lm-token"
        assert request.headers["x-api-key"] == "lm-token"
        assert json.loads(request.read()) == {
            "model": "openai/gpt-oss-120b",
            "input": "hello",
            "max_output_tokens": 64,
        }
        return httpx.Response(
            200,
            json={
                "id": "resp_123",
                "object": "response",
                "output": [{"type": "message"}],
                "usage": {"input_tokens": 9, "output_tokens": 13},
            },
        )

    executor = OpenAICompatExecutor(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    request = UnifiedInferenceRequest(
        request_id="req-resp",
        protocol="openai_responses",
        model="openai/gpt-oss-120b",
        model_profile="openai/gpt-oss-120b",
        upstream_model="openai/gpt-oss-120b",
        auth_modes=["api_key"],
        provider="openai_compat",
        payload={
            "model": "ignored-by-router",
            "input": "hello",
            "max_output_tokens": 64,
        },
        principal=_make_principal(),
        estimated_units=64,
    )

    result = executor.execute(request, _make_credential())

    assert result.body["id"] == "resp_123"
    assert result.tokens_in == 9
    assert result.tokens_out == 13


def test_openai_compat_executor_raises_invalid_credential_error_on_auth_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "invalid api key"}},
        )

    executor = OpenAICompatExecutor(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    request = UnifiedInferenceRequest(
        request_id="req-auth",
        protocol="openai_chat",
        model="zai-org/glm-4.7-flash",
        model_profile="zai-org/glm-4.7-flash",
        upstream_model="zai-org/glm-4.7-flash",
        auth_modes=["api_key"],
        provider="openai_compat",
        payload={
            "model": "ignored-by-router",
            "messages": [{"role": "user", "content": "hello"}],
        },
        principal=_make_principal(),
        estimated_units=1,
    )

    with pytest.raises(UpstreamCredentialInvalidError, match="invalid api key"):
        executor.execute(request, _make_credential())


def test_openai_compat_executor_rejects_non_json_success_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="Internal Server Error",
            headers={"content-type": "text/plain; charset=utf-8"},
        )

    executor = OpenAICompatExecutor(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    request = UnifiedInferenceRequest(
        request_id="req-non-json",
        protocol="openai_chat",
        model="minimax/minimax-m2.5",
        model_profile="minimax/minimax-m2.5",
        upstream_model="minimax-m2.5",
        auth_modes=["api_key"],
        provider="openai_compat",
        payload={
            "model": "ignored-by-router",
            "messages": [{"role": "user", "content": "hello"}],
        },
        principal=_make_principal(),
        estimated_units=1,
    )

    with pytest.raises(HTTPException, match="non-JSON") as exc_info:
        executor.execute(request, _make_credential())

    assert exc_info.value.status_code == 502


def test_openai_compat_executor_uses_longer_read_timeout_for_responses_style_upstreams() -> None:
    executor = OpenAICompatExecutor()

    with executor._client() as client:  # type: ignore[attr-defined]
        assert client.timeout.connect == 5.0
        assert client.timeout.read == 120.0
        assert client.timeout.write == 30.0
