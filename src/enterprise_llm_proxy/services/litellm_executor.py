from __future__ import annotations

import json
from typing import Iterator

import litellm

from enterprise_llm_proxy.domain.credentials import ProviderCredential
from enterprise_llm_proxy.domain.inference import UnifiedInferenceRequest
from enterprise_llm_proxy.services.execution import ExecutionResult

# Providers that store JSON {"api_key": ..., "base_url": ...} in access_token
_COMPAT_PROVIDERS = {"anthropic_compat", "openai_compat"}

_FINISH_REASON_TO_ANTHROPIC = {
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "stop_sequence",
}


def _anthropic_content_to_text(content: object) -> str:
    """Flatten Anthropic content (str or list of blocks) to a plain string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif block.get("type") == "image":
                    parts.append("[image]")
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def _anthropic_to_openai_messages(payload: dict) -> list[dict]:
    """Convert Anthropic Messages payload to OpenAI chat messages list."""
    messages: list[dict] = []
    system = payload.get("system")
    if system:
        messages.append({"role": "system", "content": _anthropic_content_to_text(system)})
    for msg in payload.get("messages", []):
        messages.append({
            "role": msg["role"],
            "content": _anthropic_content_to_text(msg.get("content", "")),
        })
    return messages


def _openai_to_anthropic_response(body: dict, original_model: str) -> dict:
    """Convert OpenAI chat.completion response body to Anthropic Messages format."""
    choice = body.get("choices", [{}])[0]
    message = choice.get("message", {})
    finish_reason = choice.get("finish_reason", "stop")
    usage = body.get("usage", {})
    return {
        "id": f"msg_{body.get('id', 'litellm')}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": message.get("content") or ""}],
        "model": original_model,
        "stop_reason": _FINISH_REASON_TO_ANTHROPIC.get(finish_reason, "end_turn"),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


class LiteLLMExecutor:
    def execute(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> ExecutionResult:
        api_key, api_base = self._parse_credential(credential)
        kwargs = self._build_kwargs(request, api_key, api_base)
        response = litellm.completion(**kwargs)
        usage = response.usage
        body = response.model_dump()
        if request.protocol == "anthropic_messages":
            body = _openai_to_anthropic_response(body, request.model)
        return ExecutionResult(
            body=body,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
        )

    def execute_stream(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> Iterator[bytes]:
        api_key, api_base = self._parse_credential(credential)
        kwargs = self._build_kwargs(request, api_key, api_base, stream=True)
        for chunk in litellm.completion(**kwargs):
            yield f"data: {chunk.model_dump_json()}\n\n".encode()
        yield b"data: [DONE]\n\n"

    def _parse_credential(
        self, credential: ProviderCredential
    ) -> tuple[str, str | None]:
        if credential.provider in _COMPAT_PROVIDERS:
            data = json.loads(credential.access_token)
            return data["api_key"], data.get("base_url")
        return credential.access_token, None

    def _build_kwargs(
        self,
        request: UnifiedInferenceRequest,
        api_key: str,
        api_base: str | None,
        stream: bool = False,
    ) -> dict:
        if request.protocol == "anthropic_messages":
            messages = _anthropic_to_openai_messages(request.payload)
        else:
            messages = request.payload.get("messages", [])

        kwargs: dict = {
            "model": request.model_profile,
            "messages": messages,
            "api_key": api_key,
            "stream": stream,
        }
        if api_base:
            kwargs["api_base"] = api_base
        max_tokens = request.payload.get("max_tokens")
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        temperature = request.payload.get("temperature")
        if temperature is not None:
            kwargs["temperature"] = temperature
        return kwargs
