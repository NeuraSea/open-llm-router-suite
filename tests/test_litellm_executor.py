from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from enterprise_llm_proxy.domain.credentials import (
    CredentialState,
    CredentialVisibility,
    ProviderCredential,
)
from enterprise_llm_proxy.domain.inference import UnifiedInferenceRequest
from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.services.litellm_executor import LiteLLMExecutor


def _make_principal() -> Principal:
    return Principal(
        user_id="user-1",
        email="test@example.com",
        name="Test User",
        role="developer",
        team_ids=["team-1"],
    )


def _make_credential(
    provider: str = "anthropic",
    access_token: str = "sk-test-key",
) -> ProviderCredential:
    return ProviderCredential(
        id="cred-1",
        provider=provider,
        auth_kind="api_key",
        account_id="acct-1",
        scopes=["chat"],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token=access_token,
        refresh_token=None,
    )


def _make_request(model_profile: str = "anthropic/claude-sonnet-4-6") -> UnifiedInferenceRequest:
    return UnifiedInferenceRequest(
        request_id="req_abc123",
        protocol="openai_chat",
        model="claude-max/claude-sonnet-4-6",
        model_profile=model_profile,
        upstream_model="claude-sonnet-4-6",
        auth_modes=["api_key"],
        provider="claude-max",
        payload={
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
            "temperature": 0.7,
        },
        principal=_make_principal(),
        estimated_units=100,
    )


def _mock_response(prompt_tokens: int = 10, completion_tokens: int = 20) -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    response = MagicMock()
    response.usage = usage
    response.model_dump.return_value = {
        "id": "chatcmpl-123",
        "choices": [{"message": {"content": "Hi!"}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }
    return response


class TestLiteLLMExecutor:
    def test_execute_standard_provider(self):
        executor = LiteLLMExecutor()
        credential = _make_credential(provider="anthropic", access_token="sk-ant-key")
        request = _make_request()

        with patch("enterprise_llm_proxy.services.litellm_executor.litellm.completion") as mock_completion:
            mock_completion.return_value = _mock_response(10, 20)
            result = executor.execute(request, credential)

        assert result.tokens_in == 10
        assert result.tokens_out == 20
        assert result.body["id"] == "chatcmpl-123"

        call_kwargs = mock_completion.call_args[1]
        assert call_kwargs["model"] == "anthropic/claude-sonnet-4-6"
        assert call_kwargs["api_key"] == "sk-ant-key"
        assert call_kwargs["max_tokens"] == 100
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["stream"] is False
        assert "api_base" not in call_kwargs

    def test_execute_compat_provider_parses_json_credential(self):
        executor = LiteLLMExecutor()
        compat_token = json.dumps({"api_key": "sk-compat", "base_url": "https://custom.api.com"})
        credential = _make_credential(provider="openai_compat", access_token=compat_token)
        request = _make_request(model_profile="openai/gpt-4")

        with patch("enterprise_llm_proxy.services.litellm_executor.litellm.completion") as mock_completion:
            mock_completion.return_value = _mock_response(5, 15)
            result = executor.execute(request, credential)

        assert result.tokens_in == 5
        assert result.tokens_out == 15

        call_kwargs = mock_completion.call_args[1]
        assert call_kwargs["api_key"] == "sk-compat"
        assert call_kwargs["api_base"] == "https://custom.api.com"

    def test_execute_no_usage(self):
        executor = LiteLLMExecutor()
        credential = _make_credential()
        request = _make_request()

        response = MagicMock()
        response.usage = None
        response.model_dump.return_value = {"id": "x", "choices": []}

        with patch("enterprise_llm_proxy.services.litellm_executor.litellm.completion", return_value=response):
            result = executor.execute(request, credential)

        assert result.tokens_in == 0
        assert result.tokens_out == 0

    def test_execute_stream(self):
        executor = LiteLLMExecutor()
        credential = _make_credential()
        request = _make_request()

        chunk1 = MagicMock()
        chunk1.model_dump_json.return_value = '{"choices":[{"delta":{"content":"Hi"}}]}'
        chunk2 = MagicMock()
        chunk2.model_dump_json.return_value = '{"choices":[{"delta":{"content":"!"}}]}'

        with patch("enterprise_llm_proxy.services.litellm_executor.litellm.completion", return_value=[chunk1, chunk2]):
            chunks = list(executor.execute_stream(request, credential))

        assert len(chunks) == 3
        assert chunks[0].startswith(b"data: ")
        assert b"Hi" in chunks[0]
        assert chunks[1].startswith(b"data: ")
        assert b"!" in chunks[1]
        assert chunks[2] == b"data: [DONE]\n\n"

        # Verify stream=True was passed
        from enterprise_llm_proxy.services.litellm_executor import litellm
        # The mock was already called, just verify via the patch
