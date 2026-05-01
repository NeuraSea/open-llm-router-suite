from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Iterator
from urllib.parse import urljoin
from urllib.parse import urlencode

import httpx

_log = logging.getLogger(__name__)
from fastapi import HTTPException, status

from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.domain.credentials import ProviderCredential
from enterprise_llm_proxy.domain.inference import UnifiedInferenceRequest
from enterprise_llm_proxy.services.execution import (
    ExecutionResult,
    MissingExecutor,
    UpstreamCredentialInvalidError,
    UpstreamRateLimitError,
    is_invalid_credential_status,
)


class OpenAIOAuthBridgeExecutor:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def execute(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> ExecutionResult:
        access_token = credential.access_token
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Selected upstream credential is missing an access token",
            )

        payload, endpoint = self._build_request(request)
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                self._url_for(endpoint),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise UpstreamRateLimitError("Upstream credential hit rate limits")
        if is_invalid_credential_status(response.status_code):
            raise UpstreamCredentialInvalidError(self._error_detail(response))
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=self._error_detail(response),
            )

        body = dict(response.json())
        if request.protocol == "anthropic_messages":
            translated = self._translate_chat_to_anthropic(body)
            return ExecutionResult(
                body=translated,
                tokens_in=int(translated["usage"]["input_tokens"]),
                tokens_out=int(translated["usage"]["output_tokens"]),
            )
        usage = body.get("usage", {})
        return ExecutionResult(
            body=body,
            tokens_in=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            tokens_out=int(
                usage.get("completion_tokens") or usage.get("output_tokens") or 0
            ),
        )

    def _build_request(
        self,
        request: UnifiedInferenceRequest,
    ) -> tuple[dict[str, object], str]:
        payload = dict(request.payload)
        payload["model"] = request.upstream_model

        if request.protocol == "openai_chat":
            return payload, "/chat/completions"
        if request.protocol == "openai_responses":
            return payload, "/responses"
        if request.protocol == "anthropic_messages":
            return self._translate_anthropic_to_chat(payload), "/chat/completions"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported protocol: {request.protocol}",
        )

    def _translate_anthropic_to_chat(self, payload: dict[str, object]) -> dict[str, object]:
        messages = payload.get("messages", [])
        translated_messages = []
        for raw_message in messages if isinstance(messages, list) else []:
            if not isinstance(raw_message, dict):
                continue
            translated_messages.append(
                {
                    "role": raw_message.get("role", "user"),
                    "content": self._flatten_content(raw_message.get("content")),
                }
            )

        request_payload: dict[str, object] = {
            "model": payload["model"],
            "messages": translated_messages,
        }
        if "max_tokens" in payload:
            request_payload["max_tokens"] = payload["max_tokens"]
        if "temperature" in payload:
            request_payload["temperature"] = payload["temperature"]
        if "system" in payload:
            request_payload["messages"] = [
                {"role": "system", "content": self._flatten_content(payload["system"])},
                *translated_messages,
            ]
        return request_payload

    def _translate_chat_to_anthropic(self, payload: dict[str, object]) -> dict[str, object]:
        choices = payload.get("choices", [])
        first_choice = choices[0] if isinstance(choices, list) and choices else {}
        message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
        usage = payload.get("usage", {})
        return {
            "id": payload.get("id", "msg_openai_bridge"),
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": self._flatten_content(message.get("content")),
                }
            ],
            "stop_reason": first_choice.get("finish_reason", "end_turn")
            if isinstance(first_choice, dict)
            else "end_turn",
            "model": payload.get("model"),
            "usage": {
                "input_tokens": int(usage.get("prompt_tokens") or 0),
                "output_tokens": int(usage.get("completion_tokens") or 0),
            },
        }

    def _url_for(self, path: str) -> str:
        base_url = self._settings.openai_api_base_url.rstrip("/") + "/"
        return urljoin(base_url, path.lstrip("/"))

    @staticmethod
    def _flatten_content(content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(part for part in parts if part)
        if isinstance(content, dict) and content.get("type") == "text":
            return str(content.get("text", ""))
        return str(content or "")

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return str(error["message"])
        return "Upstream request failed"


class OpenAICodexOAuthBridgeExecutor:
    _STATIC_UNSUPPORTED_PARAMETERS = frozenset({"temperature"})
    _UNSUPPORTED_PARAMETER_CACHE_TTL_SECONDS = 15 * 60
    _UNSUPPORTED_PARAMETER_PATTERNS = (
        re.compile(
            r"(?:unsupported|unknown|unrecognized)\s+(?:parameter|field)"
            r"[:\s]+[`'\"]?([A-Za-z_][\w.-]*)[`'\"]?",
            re.IGNORECASE,
        ),
        re.compile(
            r"[`'\"]([A-Za-z_][\w.-]*)[`'\"]\s+(?:is|are)\s+not\s+supported",
            re.IGNORECASE,
        ),
    )

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._unsupported_parameter_cache: dict[tuple[str, str, str], dict[str, float]] = {}

    def _client_kwargs(self) -> dict[str, object]:
        transport = self._settings.openai_codex_transport.strip().lower()
        proxy_url = (
            os.getenv("HTTPS_PROXY")
            or os.getenv("https_proxy")
            or os.getenv("HTTP_PROXY")
            or os.getenv("http_proxy")
        )
        if transport == "direct":
            return {"timeout": 30.0, "trust_env": False}
        if transport in {"proxy", "auto"} and proxy_url:
            return {"timeout": 30.0, "trust_env": False, "proxy": proxy_url}
        return {"timeout": 30.0}

    def execute(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> ExecutionResult:
        access_token = credential.access_token
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Selected upstream credential is missing an access token",
            )

        payload, endpoint = self._build_request(request)
        retried_compatibility = False
        try:
            while True:
                try:
                    body = self._execute_payload(access_token, payload, endpoint)
                    break
                except HTTPException as exc:
                    if retried_compatibility:
                        raise
                    unsupported = self._unsupported_parameter_from_exception(exc)
                    if unsupported is None or unsupported not in payload:
                        raise
                    self._remember_unsupported_parameter(request, unsupported)
                    payload = self._drop_payload_parameters(
                        request,
                        payload,
                        {unsupported},
                    )
                    retried_compatibility = True
        except UpstreamRateLimitError:
            raise
        except HTTPException:
            raise
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Upstream request failed: {exc}",
            ) from exc

        usage = self._usage_for(body)
        if request.protocol == "anthropic_messages":
            translated = self._translate_responses_to_anthropic(body)
            return ExecutionResult(
                body=translated,
                tokens_in=usage["input_tokens"],
                tokens_out=usage["output_tokens"],
            )
        if request.protocol == "openai_chat":
            translated = self._translate_responses_to_chat(body)
            return ExecutionResult(
                body=translated,
                tokens_in=usage["input_tokens"],
                tokens_out=usage["output_tokens"],
            )
        return ExecutionResult(
            body=body,
            tokens_in=usage["input_tokens"],
            tokens_out=usage["output_tokens"],
        )

    def execute_stream(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> Iterator[bytes]:
        access_token = credential.access_token
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Selected upstream credential is missing an access token",
            )

        payload, endpoint = self._build_request(request)
        retried_compatibility = False
        try:
            while True:
                emitted = False
                try:
                    for chunk in self._stream_payload(
                        access_token,
                        payload,
                        endpoint,
                        request,
                    ):
                        emitted = True
                        yield chunk
                    return
                except HTTPException as exc:
                    if retried_compatibility or emitted:
                        raise
                    unsupported = self._unsupported_parameter_from_exception(exc)
                    if unsupported is None or unsupported not in payload:
                        raise
                    self._remember_unsupported_parameter(request, unsupported)
                    payload = self._drop_payload_parameters(
                        request,
                        payload,
                        {unsupported},
                    )
                    retried_compatibility = True
        except UpstreamRateLimitError:
            raise
        except HTTPException:
            raise
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Upstream request failed: {exc}",
            ) from exc

    def _build_request(
        self,
        request: UnifiedInferenceRequest,
    ) -> tuple[dict[str, object], str]:
        if request.protocol == "openai_responses":
            payload = dict(request.payload)
            payload["model"] = request.upstream_model
            payload.setdefault("store", False)
            payload["stream"] = True
            payload.setdefault("instructions", "")
            payload.pop("transport", None)
            payload.pop("max_output_tokens", None)
            payload.pop("max_tokens", None)
            return (
                self._sanitize_payload(request, payload),
                self._settings.openai_codex_responses_path,
            )
        if request.protocol == "openai_chat":
            payload = self._translate_chat_to_responses(
                request.payload,
                upstream_model=request.upstream_model,
            )
            return (
                self._sanitize_payload(request, payload),
                self._settings.openai_codex_responses_path,
            )
        if request.protocol == "anthropic_messages":
            payload = self._translate_anthropic_to_responses(
                request.payload,
                upstream_model=request.upstream_model,
            )
            return (
                self._sanitize_payload(request, payload),
                self._settings.openai_codex_responses_path,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported protocol: {request.protocol}",
        )

    def _execute_payload(
        self,
        access_token: str,
        payload: dict[str, object],
        endpoint: str,
    ) -> dict[str, object]:
        with httpx.Client(**self._client_kwargs()) as client:
            with client.stream(
                "POST",
                self._url_for(endpoint),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=payload,
            ) as response:
                if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    raise UpstreamRateLimitError("Upstream credential hit rate limits")
                if is_invalid_credential_status(response.status_code):
                    response.read()
                    raise UpstreamCredentialInvalidError(
                        OpenAIOAuthBridgeExecutor._error_detail(response)
                    )
                if response.status_code >= 400:
                    response.read()
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=OpenAIOAuthBridgeExecutor._error_detail(response),
                    )
                return self._parse_sse_payload(response.iter_lines())

    def _stream_payload(
        self,
        access_token: str,
        payload: dict[str, object],
        endpoint: str,
        request: UnifiedInferenceRequest,
    ) -> Iterator[bytes]:
        with httpx.Client(**self._client_kwargs()) as client:
            with client.stream(
                "POST",
                self._url_for(endpoint),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=payload,
            ) as response:
                if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    raise UpstreamRateLimitError("Upstream credential hit rate limits")
                if is_invalid_credential_status(response.status_code):
                    response.read()
                    raise UpstreamCredentialInvalidError(
                        OpenAIOAuthBridgeExecutor._error_detail(response)
                    )
                if response.status_code >= 400:
                    response.read()
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=OpenAIOAuthBridgeExecutor._error_detail(response),
                    )

                if request.protocol == "openai_chat":
                    yield from self._responses_sse_to_chat_chunks(response.iter_lines())
                    return
                if request.protocol == "anthropic_messages":
                    yield from self._responses_sse_to_anthropic_events(
                        response.iter_lines()
                    )
                    return

                yield from self._forward_responses_sse_lines(response.iter_lines())

    def _sanitize_payload(
        self,
        request: UnifiedInferenceRequest,
        payload: dict[str, object],
    ) -> dict[str, object]:
        unsupported = set(self._STATIC_UNSUPPORTED_PARAMETERS)
        unsupported.update(self._cached_unsupported_parameters(request))
        return self._drop_payload_parameters(request, payload, unsupported)

    def _drop_payload_parameters(
        self,
        request: UnifiedInferenceRequest,
        payload: dict[str, object],
        parameter_names: set[str],
    ) -> dict[str, object]:
        filtered = sorted(name for name in parameter_names if name in payload)
        if not filtered:
            return payload
        sanitized = dict(payload)
        for name in filtered:
            sanitized.pop(name, None)
        _log.info(
            "Filtered unsupported Codex upstream parameters",
            extra={
                "request_id": request.request_id,
                "model_profile": request.model_profile,
                "provider": request.provider,
                "filtered_params": filtered,
            },
        )
        return sanitized

    def _cached_unsupported_parameters(
        self,
        request: UnifiedInferenceRequest,
    ) -> set[str]:
        key = self._compatibility_cache_key(request)
        cached = self._unsupported_parameter_cache.get(key, {})
        now = time.monotonic()
        expired = [name for name, expires_at in cached.items() if expires_at <= now]
        for name in expired:
            cached.pop(name, None)
        return set(cached)

    def _remember_unsupported_parameter(
        self,
        request: UnifiedInferenceRequest,
        parameter_name: str,
    ) -> None:
        key = self._compatibility_cache_key(request)
        expires_at = time.monotonic() + self._UNSUPPORTED_PARAMETER_CACHE_TTL_SECONDS
        self._unsupported_parameter_cache.setdefault(key, {})[parameter_name] = expires_at

    @staticmethod
    def _compatibility_cache_key(
        request: UnifiedInferenceRequest,
    ) -> tuple[str, str, str]:
        return (request.provider, request.protocol, request.upstream_model)

    @classmethod
    def _unsupported_parameter_from_exception(
        cls,
        exc: HTTPException,
    ) -> str | None:
        detail = exc.detail
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("detail") or detail.get("error")
        if not isinstance(detail, str):
            return None
        for pattern in cls._UNSUPPORTED_PARAMETER_PATTERNS:
            match = pattern.search(detail)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _forward_responses_sse_lines(lines: object) -> Iterator[bytes]:
        current_event: str | None = None
        current_data: list[str] = []
        buffered_lines: list[str] = []

        def encode_buffered_lines() -> list[bytes]:
            return [
                f"{line}\n".encode("utf-8") if line else b"\n"
                for line in buffered_lines
            ]

        def flush_event() -> list[bytes]:
            nonlocal current_event, current_data, buffered_lines
            if not buffered_lines:
                return []
            current_event_name = current_event or "message"
            raw_data = "\n".join(current_data).strip()
            if current_event_name == "response.failed":
                detail = "Upstream request failed"
                if raw_data and raw_data != "[DONE]":
                    try:
                        payload = json.loads(raw_data)
                    except json.JSONDecodeError:
                        payload = None
                    error = payload.get("error") if isinstance(payload, dict) else None
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        detail = str(error["message"])
                current_event = None
                current_data = []
                buffered_lines = []
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
            encoded = encode_buffered_lines()
            current_event = None
            current_data = []
            buffered_lines = []
            return encoded

        for raw_line in lines:
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
            buffered_lines.append(line)
            if line.startswith("event:"):
                current_event = line.partition(":")[2].strip()
            elif line.startswith("data:"):
                current_data.append(line.partition(":")[2].lstrip())

            if not line:
                for chunk in flush_event():
                    yield chunk

        for chunk in flush_event():
            yield chunk

    def _translate_chat_to_responses(
        self,
        payload: dict[str, object],
        *,
        upstream_model: str,
    ) -> dict[str, object]:
        translated_messages = []
        for raw_message in payload.get("messages", []) if isinstance(payload.get("messages"), list) else []:
            if not isinstance(raw_message, dict):
                continue
            role = str(raw_message.get("role", "user"))
            translated_messages.append(
                {
                    "role": role,
                    "content": self._to_responses_blocks(raw_message.get("content"), role=role),
                }
            )

        system_message = self._extract_system_message(payload)
        request_payload: dict[str, object] = {
            "model": upstream_model,
            "input": translated_messages,
            "store": False,
            "stream": True,
            "instructions": system_message or "",
        }
        if "temperature" in payload:
            request_payload["temperature"] = payload["temperature"]
        return request_payload

    def _translate_anthropic_to_responses(
        self,
        payload: dict[str, object],
        *,
        upstream_model: str,
    ) -> dict[str, object]:
        translated_messages: list[dict[str, object]] = []
        for raw_message in payload.get("messages", []) if isinstance(payload.get("messages"), list) else []:
            if not isinstance(raw_message, dict):
                continue
            translated_messages.extend(self._anthropic_message_to_responses_input_items(raw_message))

        request_payload: dict[str, object] = {
            "model": upstream_model,
            "input": translated_messages,
            "store": False,
            "stream": True,
            "instructions": "",
        }
        if "temperature" in payload:
            request_payload["temperature"] = payload["temperature"]
        if "system" in payload:
            request_payload["instructions"] = OpenAIOAuthBridgeExecutor._flatten_content(
                payload["system"]
            )
        translated_tools = self._anthropic_tools_to_responses(
            payload.get("tools"),
            payload.get("mcp_servers"),
        )
        if translated_tools:
            request_payload["tools"] = translated_tools
        translated_tool_choice = self._anthropic_tool_choice_to_responses(
            payload.get("tool_choice")
        )
        if translated_tool_choice is not None:
            request_payload["tool_choice"] = translated_tool_choice
        return request_payload

    @staticmethod
    def _parse_sse_payload(lines: object) -> dict[str, object]:
        current_event: str | None = None
        current_data: list[str] = []
        latest_response: dict[str, object] | None = None
        output_items: dict[int, dict[str, object]] = {}
        output_order: list[int] = []
        output_text_parts: list[str] = []

        def remember_output_item(output_index: int, item: dict[str, object]) -> None:
            output_items[output_index] = dict(item)
            if output_index not in output_order:
                output_order.append(output_index)

        def finalize_event() -> dict[str, object] | None:
            nonlocal current_event, current_data, latest_response
            if not current_data:
                current_event = None
                return None
            raw_data = "\n".join(current_data).strip()
            current_event = current_event or "message"
            current_data = []
            if raw_data == "[DONE]":
                current_event = None
                return None
            payload = json.loads(raw_data)
            current_event_name = current_event
            current_event = None

            if current_event_name == "response.failed":
                error = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    detail = str(error["message"])
                else:
                    detail = "Upstream request failed"
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)

            if current_event_name == "response.output_item.done" and isinstance(payload, dict):
                item = payload.get("item")
                output_index = payload.get("output_index")
                if isinstance(item, dict) and isinstance(output_index, int):
                    remember_output_item(output_index, item)
                return None

            if current_event_name == "response.output_text.done" and isinstance(payload, dict):
                text = payload.get("text")
                if isinstance(text, str):
                    output_text_parts.append(text)
                return None

            if current_event_name in {
                "response.mcp_call.completed",
                "response.mcp_call.failed",
            } and isinstance(payload, dict):
                item = payload.get("item")
                if not isinstance(item, dict):
                    item = payload.get("mcp_call")
                if isinstance(item, dict):
                    output_index = payload.get("output_index")
                    if not isinstance(output_index, int):
                        output_index = max(output_order, default=-1) + 1
                    mcp_item = dict(item)
                    mcp_item.setdefault("type", "mcp_call")
                    if current_event_name == "response.mcp_call.failed":
                        mcp_item.setdefault("status", "failed")
                        if "error" not in mcp_item:
                            error = payload.get("error")
                            if isinstance(error, dict) and isinstance(error.get("message"), str):
                                mcp_item["error"] = str(error["message"])
                            elif isinstance(error, str) and error:
                                mcp_item["error"] = error
                            else:
                                mcp_item["error"] = "MCP tool call failed"
                    remember_output_item(output_index, mcp_item)
                return None

            response_payload = payload.get("response") if isinstance(payload, dict) else None
            if isinstance(response_payload, dict):
                latest_response = dict(response_payload)
                if output_items:
                    latest_response["output"] = [output_items[index] for index in sorted(output_order)]
                if output_text_parts:
                    latest_response["output_text"] = "".join(output_text_parts)
                if current_event_name == "response.completed":
                    return latest_response
            return None

        for raw_line in lines:
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
            if not line:
                completed = finalize_event()
                if completed is not None:
                    return completed
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                current_event = line.partition(":")[2].strip()
                continue
            if line.startswith("data:"):
                current_data.append(line.partition(":")[2].lstrip())

        completed = finalize_event()
        if completed is not None:
            return completed
        if latest_response is not None:
            return latest_response
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream request failed: missing response.completed event",
        )

    @staticmethod
    def _responses_sse_to_chat_chunks(lines: object) -> Iterator[bytes]:
        current_event: str | None = None
        current_data: list[str] = []
        response_id = "chatcmpl_openai_codex"
        model: str | None = None
        role_emitted = False

        def encode_chunk(
            *,
            delta: dict[str, object],
            finish_reason: str | None = None,
        ) -> bytes:
            chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish_reason,
                    }
                ],
            }
            return f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n".encode("utf-8")

        def finalize_event() -> list[bytes]:
            nonlocal current_event, current_data, response_id, model, role_emitted
            if not current_data:
                current_event = None
                return []

            raw_data = "\n".join(current_data).strip()
            current_event_name = current_event or "message"
            current_event = None
            current_data = []

            if raw_data == "[DONE]":
                return [b"data: [DONE]\n\n"]

            payload = json.loads(raw_data)
            emitted: list[bytes] = []

            if current_event_name == "response.failed" and isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    detail = str(error["message"])
                else:
                    detail = "Upstream request failed"
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)

            response_payload = payload.get("response") if isinstance(payload, dict) else None
            if isinstance(response_payload, dict):
                response_id = str(response_payload.get("id") or response_id)
                if isinstance(response_payload.get("model"), str):
                    model = str(response_payload["model"])

            if current_event_name == "response.output_item.added" and isinstance(payload, dict):
                item = payload.get("item")
                if (
                    not role_emitted
                    and isinstance(item, dict)
                    and item.get("type") == "message"
                    and item.get("role") == "assistant"
                ):
                    emitted.append(encode_chunk(delta={"role": "assistant"}))
                    role_emitted = True

            if current_event_name == "response.output_text.delta" and isinstance(payload, dict):
                delta = payload.get("delta")
                if isinstance(delta, str) and delta:
                    emitted.append(encode_chunk(delta={"content": delta}))

            if current_event_name == "response.completed" and isinstance(payload, dict):
                emitted.append(encode_chunk(delta={}, finish_reason="end_turn"))
                emitted.append(b"data: [DONE]\n\n")

            return emitted

        for raw_line in lines:
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
            if not line:
                for chunk in finalize_event():
                    yield chunk
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                current_event = line.partition(":")[2].strip()
                continue
            if line.startswith("data:"):
                current_data.append(line.partition(":")[2].lstrip())

        for chunk in finalize_event():
            yield chunk

    @staticmethod
    def _responses_sse_to_anthropic_events(lines: object) -> Iterator[bytes]:
        current_event: str | None = None
        current_data: list[str] = []
        message_id = "msg_openai_codex_bridge"
        model: str | None = None
        message_started = False
        message_stopped = False
        tool_use_emitted = False
        approval_request_emitted = False
        next_content_index = 0
        output_states: dict[int, dict[str, object]] = {}

        def encode_event(event_name: str, payload: dict[str, object]) -> bytes:
            return (
                f"event: {event_name}\n"
                f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
            ).encode("utf-8")

        def ensure_message_start() -> list[bytes]:
            nonlocal message_started
            if message_started:
                return []
            message_started = True
            return [
                encode_event(
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": message_id,
                            "type": "message",
                            "role": "assistant",
                            "model": model,
                            "usage": {"input_tokens": 0, "output_tokens": 0},
                        },
                    },
                )
            ]

        def block_state(output_index: int) -> dict[str, object]:
            return output_states.setdefault(
                output_index,
                {
                    "kind": None,
                    "started": False,
                    "closed": False,
                    "result_emitted": False,
                    "content_index": None,
                    "call_id": "",
                    "name": "",
                    "server_label": "",
                    "arguments": [],
                },
            )

        def allocate_content_index(
            state: dict[str, object],
            key: str = "content_index",
        ) -> int:
            nonlocal next_content_index
            existing = state.get(key)
            if isinstance(existing, int):
                return existing
            index = next_content_index
            next_content_index += 1
            state[key] = index
            return index

        def start_text_block(output_index: int) -> list[bytes]:
            state = block_state(output_index)
            if state["started"]:
                return []
            content_index = allocate_content_index(state)
            state["kind"] = "text"
            state["started"] = True
            emitted = ensure_message_start()
            emitted.append(
                encode_event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": content_index,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            )
            return emitted

        def start_tool_block(output_index: int) -> list[bytes]:
            nonlocal tool_use_emitted
            state = block_state(output_index)
            if state["started"]:
                return []
            content_index = allocate_content_index(state)
            state["kind"] = "tool_use"
            state["started"] = True
            tool_use_emitted = True
            emitted = ensure_message_start()
            emitted.append(
                encode_event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": content_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": state["call_id"],
                            "name": state["name"],
                            "input": {},
                        },
                    },
                )
            )
            return emitted

        def start_mcp_tool_block(output_index: int) -> list[bytes]:
            state = block_state(output_index)
            if state["started"]:
                return []
            content_index = allocate_content_index(state)
            state["kind"] = "mcp_tool_use"
            state["started"] = True
            emitted = ensure_message_start()
            emitted.append(
                encode_event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": content_index,
                        "content_block": {
                            "type": "mcp_tool_use",
                            "id": state["call_id"],
                            "server_name": state["server_label"],
                            "name": state["name"],
                            "input": {},
                        },
                    },
                )
            )
            return emitted

        def emit_transient_content_block(content_block: dict[str, object]) -> list[bytes]:
            nonlocal next_content_index
            content_index = next_content_index
            next_content_index += 1
            emitted = ensure_message_start()
            emitted.append(
                encode_event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": content_index,
                        "content_block": content_block,
                    },
                )
            )
            emitted.append(
                encode_event(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": content_index},
                )
            )
            return emitted

        def close_block(output_index: int) -> list[bytes]:
            state = block_state(output_index)
            if not state["started"] or state["closed"]:
                return []
            content_index = state.get("content_index")
            if not isinstance(content_index, int):
                return []
            state["closed"] = True
            return [
                encode_event(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": content_index},
                )
            ]

        def emit_message_stop(
            *,
            stop_reason: str,
            usage: dict[str, object] | None = None,
        ) -> list[bytes]:
            nonlocal message_stopped
            if message_stopped:
                return []
            emitted = ensure_message_start()
            for output_index in sorted(output_states):
                emitted.extend(close_block(output_index))
            emitted.append(
                encode_event(
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": stop_reason},
                        "usage": usage or {"input_tokens": 0, "output_tokens": 0},
                    },
                )
            )
            emitted.append(encode_event("message_stop", {"type": "message_stop"}))
            message_stopped = True
            return emitted

        def incomplete_stop_reason(response_payload: dict[str, object] | None) -> str:
            if not isinstance(response_payload, dict):
                return "end_turn"
            details = response_payload.get("incomplete_details")
            if not isinstance(details, dict):
                return "end_turn"
            reason = details.get("reason")
            if reason in {"max_output_tokens", "max_tokens"}:
                return "max_tokens"
            return "end_turn"

        def finalize_event() -> list[bytes]:
            nonlocal current_event, current_data, message_id, model, approval_request_emitted
            if not current_data:
                current_event = None
                return []

            raw_data = "\n".join(current_data).strip()
            current_event_name = current_event or "message"
            current_event = None
            current_data = []

            if raw_data == "[DONE]":
                return []

            payload = json.loads(raw_data)
            emitted: list[bytes] = []

            if current_event_name == "response.failed" and isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    detail = str(error["message"])
                else:
                    detail = "Upstream request failed"
                return [
                    encode_event(
                        "error",
                        {
                            "type": "error",
                            "error": {"type": "api_error", "message": detail},
                        },
                    )
                ]

            response_payload = payload.get("response") if isinstance(payload, dict) else None
            if isinstance(response_payload, dict):
                message_id = str(response_payload.get("id") or message_id)
                if isinstance(response_payload.get("model"), str):
                    model = str(response_payload["model"])

            if current_event_name == "response.output_item.added" and isinstance(payload, dict):
                item = payload.get("item")
                output_index = payload.get("output_index")
                if isinstance(item, dict) and isinstance(output_index, int):
                    state = block_state(output_index)
                    if item.get("type") == "function_call":
                        state["kind"] = "tool_use"
                        state["call_id"] = str(item.get("call_id") or item.get("id") or "")
                        state["name"] = str(item.get("name") or "")
                    elif item.get("type") == "mcp_call":
                        state["kind"] = "mcp_tool_use"
                        state["call_id"] = str(item.get("id") or "")
                        state["name"] = str(item.get("name") or "")
                        state["server_label"] = str(item.get("server_label") or "")
                    elif item.get("type") == "message":
                        state["kind"] = "text"

            if current_event_name == "response.output_text.delta" and isinstance(payload, dict):
                output_index = payload.get("output_index")
                delta = payload.get("delta")
                if isinstance(output_index, int) and isinstance(delta, str) and delta:
                    emitted.extend(start_text_block(output_index))
                    content_index = allocate_content_index(block_state(output_index))
                    emitted.append(
                        encode_event(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": content_index,
                                "delta": {"type": "text_delta", "text": delta},
                            },
                        )
                    )

            if (
                current_event_name == "response.function_call_arguments.delta"
                and isinstance(payload, dict)
            ):
                output_index = payload.get("output_index")
                delta = payload.get("delta")
                if isinstance(output_index, int) and isinstance(delta, str):
                    state = block_state(output_index)
                    state["arguments"].append(delta)
                    emitted.extend(start_tool_block(output_index))
                    content_index = allocate_content_index(state)
                    emitted.append(
                        encode_event(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": content_index,
                                "delta": {"type": "input_json_delta", "partial_json": delta},
                            },
                        )
                    )

            if (
                current_event_name == "response.mcp_call_arguments.delta"
                and isinstance(payload, dict)
            ):
                output_index = payload.get("output_index")
                delta = payload.get("delta")
                if isinstance(output_index, int) and isinstance(delta, str):
                    state = block_state(output_index)
                    state["arguments"].append(delta)
                    emitted.extend(start_mcp_tool_block(output_index))
                    content_index = allocate_content_index(state)
                    emitted.append(
                        encode_event(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": content_index,
                                "delta": {"type": "input_json_delta", "partial_json": delta},
                            },
                        )
                    )

            if current_event_name == "response.output_item.done" and isinstance(payload, dict):
                item = payload.get("item")
                output_index = payload.get("output_index")
                if isinstance(item, dict) and isinstance(output_index, int):
                    state = block_state(output_index)
                    item_type = item.get("type")
                    if item_type == "function_call":
                        state["kind"] = "tool_use"
                        state["call_id"] = str(item.get("call_id") or item.get("id") or "")
                        state["name"] = str(item.get("name") or "")
                        arguments = item.get("arguments")
                        if not state["started"]:
                            emitted.extend(start_tool_block(output_index))
                        if isinstance(arguments, str) and arguments and not state["arguments"]:
                            state["arguments"].append(arguments)
                            content_index = allocate_content_index(state)
                            emitted.append(
                                encode_event(
                                    "content_block_delta",
                                    {
                                        "type": "content_block_delta",
                                        "index": content_index,
                                        "delta": {
                                            "type": "input_json_delta",
                                            "partial_json": arguments,
                                        },
                                    },
                                )
                            )
                        emitted.extend(close_block(output_index))
                    elif item_type == "mcp_call":
                        state["kind"] = "mcp_tool_use"
                        state["call_id"] = str(item.get("id") or "")
                        state["name"] = str(item.get("name") or "")
                        state["server_label"] = str(item.get("server_label") or "")
                        arguments = item.get("arguments")
                        if not state["started"]:
                            emitted.extend(start_mcp_tool_block(output_index))
                        if isinstance(arguments, str) and arguments and not state["arguments"]:
                            state["arguments"].append(arguments)
                            content_index = allocate_content_index(state)
                            emitted.append(
                                encode_event(
                                    "content_block_delta",
                                    {
                                        "type": "content_block_delta",
                                        "index": content_index,
                                        "delta": {
                                            "type": "input_json_delta",
                                            "partial_json": arguments,
                                        },
                                    },
                                )
                            )
                        emitted.extend(close_block(output_index))
                        if (
                            ("output" in item or "error" in item or item.get("status") == "failed")
                            and not state["result_emitted"]
                        ):
                            state["result_emitted"] = True
                            emitted.extend(
                                emit_transient_content_block(
                                    OpenAICodexOAuthBridgeExecutor._responses_mcp_call_result_to_anthropic_block(
                                        item
                                    )
                                )
                            )
                    elif item_type == "mcp_approval_request":
                        approval_request_emitted = True
                        emitted.extend(
                            emit_transient_content_block(
                                OpenAICodexOAuthBridgeExecutor._responses_mcp_approval_request_to_anthropic_block(
                                    item
                                )
                            )
                        )
                    elif item_type == "message":
                        content = item.get("content")
                        text_parts: list[str] = []
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") in {
                                    "output_text",
                                    "text",
                                }:
                                    text_parts.append(str(block.get("text", "")))
                        if text_parts and not state["started"]:
                            emitted.extend(start_text_block(output_index))
                            for text in text_parts:
                                if not text:
                                    continue
                                emitted.append(
                                    encode_event(
                                        "content_block_delta",
                                        {
                                            "type": "content_block_delta",
                                            "index": allocate_content_index(state),
                                            "delta": {
                                                "type": "text_delta",
                                                "text": text,
                                            },
                                        },
                                    )
                                )
                        emitted.extend(close_block(output_index))

            if current_event_name in {
                "response.mcp_call.completed",
                "response.mcp_call.failed",
            } and isinstance(payload, dict):
                item = payload.get("item")
                if not isinstance(item, dict):
                    item = payload.get("mcp_call")
                output_index = payload.get("output_index")
                if isinstance(item, dict) and isinstance(output_index, int):
                    state = block_state(output_index)
                    item = dict(item)
                    item.setdefault("type", "mcp_call")
                    if current_event_name == "response.mcp_call.failed":
                        item.setdefault("status", "failed")
                        item.setdefault("error", "MCP tool call failed")
                    state["kind"] = "mcp_tool_use"
                    state["call_id"] = str(item.get("id") or "")
                    state["name"] = str(item.get("name") or "")
                    state["server_label"] = str(item.get("server_label") or "")
                    arguments = item.get("arguments")
                    if not state["started"]:
                        emitted.extend(start_mcp_tool_block(output_index))
                    if isinstance(arguments, str) and arguments and not state["arguments"]:
                        state["arguments"].append(arguments)
                        content_index = allocate_content_index(state)
                        emitted.append(
                            encode_event(
                                "content_block_delta",
                                {
                                    "type": "content_block_delta",
                                    "index": content_index,
                                    "delta": {
                                        "type": "input_json_delta",
                                        "partial_json": arguments,
                                    },
                                },
                            )
                        )
                    emitted.extend(close_block(output_index))
                    if (
                        ("output" in item or "error" in item or item.get("status") == "failed")
                        and not state["result_emitted"]
                    ):
                        state["result_emitted"] = True
                        emitted.extend(
                            emit_transient_content_block(
                                OpenAICodexOAuthBridgeExecutor._responses_mcp_call_result_to_anthropic_block(
                                    item
                                )
                            )
                        )

            if current_event_name == "response.completed" and isinstance(payload, dict):
                usage = response_payload.get("usage") if isinstance(response_payload, dict) else None
                if not isinstance(usage, dict):
                    usage = {"input_tokens": 0, "output_tokens": 0}
                emitted.extend(
                    emit_message_stop(
                        stop_reason="tool_use"
                        if tool_use_emitted or approval_request_emitted
                        else "end_turn",
                        usage=usage,
                    )
                )

            if current_event_name == "response.incomplete" and isinstance(payload, dict):
                usage = response_payload.get("usage") if isinstance(response_payload, dict) else None
                if not isinstance(usage, dict):
                    usage = {"input_tokens": 0, "output_tokens": 0}
                emitted.extend(
                    emit_message_stop(
                        stop_reason=incomplete_stop_reason(response_payload),
                        usage=usage,
                    )
                )

            return emitted

        for raw_line in lines:
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
            if not line:
                for chunk in finalize_event():
                    yield chunk
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                current_event = line.partition(":")[2].strip()
                continue
            if line.startswith("data:"):
                current_data.append(line.partition(":")[2].lstrip())

        for chunk in finalize_event():
            yield chunk

    def _translate_responses_to_chat(self, payload: dict[str, object]) -> dict[str, object]:
        usage = self._usage_for(payload)
        text = self._extract_output_text(payload)
        return {
            "id": payload.get("id", "resp_openai_codex"),
            "object": "chat.completion",
            "model": payload.get("model"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": self._finish_reason(payload),
                }
            ],
            "usage": {
                "prompt_tokens": usage["input_tokens"],
                "completion_tokens": usage["output_tokens"],
                "total_tokens": usage["input_tokens"] + usage["output_tokens"],
            },
        }

    def _translate_responses_to_anthropic(self, payload: dict[str, object]) -> dict[str, object]:
        usage = self._usage_for(payload)
        content = self._responses_output_to_anthropic_content(payload)
        return {
            "id": payload.get("id", "msg_openai_codex_bridge"),
            "type": "message",
            "role": "assistant",
            "content": content,
            "stop_reason": self._anthropic_stop_reason_for_content(payload, content),
            "model": payload.get("model"),
            "usage": usage,
        }

    def _url_for(self, path: str) -> str:
        base_url = self._settings.openai_codex_api_base_url.rstrip("/") + "/"
        return urljoin(base_url, path.lstrip("/"))

    @staticmethod
    def _extract_system_message(payload: dict[str, object]) -> str | None:
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return None
        for raw_message in messages:
            if isinstance(raw_message, dict) and raw_message.get("role") == "system":
                return OpenAIOAuthBridgeExecutor._flatten_content(raw_message.get("content"))
        return None

    @staticmethod
    def _to_responses_blocks(content: object, *, role: str = "user") -> list[dict[str, str]]:
        block_type = "output_text" if role == "assistant" else "input_text"
        blocks: list[dict[str, str]] = []
        if isinstance(content, str):
            return [{"type": block_type, "text": content}]
        if isinstance(content, dict) and content.get("type") == "text":
            return [{"type": block_type, "text": str(content.get("text", ""))}]
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    blocks.append({"type": block_type, "text": str(block.get("text", ""))})
                elif isinstance(block, str):
                    blocks.append({"type": block_type, "text": block})
        return blocks or [{"type": block_type, "text": OpenAIOAuthBridgeExecutor._flatten_content(content)}]

    @classmethod
    def _anthropic_message_to_responses_input_items(
        cls,
        message: dict[str, object],
    ) -> list[dict[str, object]]:
        role = str(message.get("role", "user"))
        content = message.get("content")
        if not isinstance(content, list):
            return [
                {
                    "role": role,
                    "content": cls._to_responses_blocks(content, role=role),
                }
            ]

        items: list[dict[str, object]] = []
        message_blocks: list[object] = []
        mcp_call_positions: dict[str, int] = {}

        def flush_message_blocks() -> None:
            if not message_blocks:
                return
            items.append(
                {
                    "role": role,
                    "content": cls._to_responses_blocks(message_blocks, role=role),
                }
            )
            message_blocks.clear()

        for block in content:
            if not isinstance(block, dict):
                message_blocks.append(block)
                continue

            block_type = block.get("type")
            if role == "assistant" and block_type == "tool_use":
                flush_message_blocks()
                items.append(
                    {
                        "type": "function_call",
                        "call_id": str(block.get("id") or ""),
                        "name": str(block.get("name") or ""),
                        "arguments": json.dumps(
                            block.get("input") if block.get("input") is not None else {},
                            separators=(",", ":"),
                        ),
                    }
                )
                continue

            if role == "assistant" and block_type == "mcp_tool_use":
                flush_message_blocks()
                mcp_call = cls._anthropic_mcp_tool_use_to_responses_call(block)
                mcp_call_id = str(mcp_call.get("id") or "")
                if mcp_call_id:
                    mcp_call_positions[mcp_call_id] = len(items)
                items.append(mcp_call)
                continue

            if block_type == "mcp_tool_result":
                flush_message_blocks()
                cls._apply_anthropic_mcp_tool_result_to_responses_call(
                    items,
                    mcp_call_positions,
                    block,
                )
                continue

            if role == "user" and block_type == "tool_result":
                flush_message_blocks()
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": str(block.get("tool_use_id") or ""),
                        "output": cls._anthropic_tool_result_to_responses_output(
                            block.get("content"),
                            is_error=bool(block.get("is_error")),
                        ),
                    }
                )
                continue

            if role == "user" and block_type == "mcp_approval_response":
                flush_message_blocks()
                items.append(cls._anthropic_mcp_approval_response_to_responses(block))
                continue

            message_blocks.append(block)

        flush_message_blocks()
        return items

    @classmethod
    def _anthropic_mcp_tool_use_to_responses_call(
        cls,
        block: dict[str, object],
    ) -> dict[str, object]:
        item: dict[str, object] = {
            "type": "mcp_call",
            "id": str(block.get("id") or ""),
            "server_label": str(block.get("server_name") or block.get("server_label") or ""),
            "name": str(block.get("name") or ""),
            "arguments": cls._json_dumps_compact(
                block.get("input") if block.get("input") is not None else {}
            ),
        }
        status_value = block.get("status")
        if isinstance(status_value, str) and status_value:
            item["status"] = status_value
        return item

    @classmethod
    def _apply_anthropic_mcp_tool_result_to_responses_call(
        cls,
        items: list[dict[str, object]],
        mcp_call_positions: dict[str, int],
        block: dict[str, object],
    ) -> None:
        tool_use_id = str(block.get("tool_use_id") or "")
        if not tool_use_id or tool_use_id not in mcp_call_positions:
            return

        item = items[mcp_call_positions[tool_use_id]]
        result = cls._anthropic_mcp_tool_result_to_responses_result(block)
        item.update(result)

    @classmethod
    def _anthropic_mcp_tool_result_to_responses_result(
        cls,
        block: dict[str, object],
    ) -> dict[str, object]:
        content = OpenAIOAuthBridgeExecutor._flatten_content(block.get("content"))
        if block.get("is_error"):
            return {
                "error": content or "MCP tool call failed",
                "status": "failed",
            }
        return {
            "output": content,
            "status": "completed",
        }

    @staticmethod
    def _anthropic_mcp_approval_response_to_responses(
        block: dict[str, object],
    ) -> dict[str, object]:
        item: dict[str, object] = {
            "type": "mcp_approval_response",
            "approval_request_id": str(block.get("approval_request_id") or ""),
            "approve": bool(block.get("approve")),
        }
        approval_id = block.get("id")
        if isinstance(approval_id, str) and approval_id:
            item["id"] = approval_id
        reason = block.get("reason")
        if isinstance(reason, str) and reason:
            item["reason"] = reason
        return item

    @classmethod
    def _anthropic_tool_result_to_responses_output(
        cls,
        content: object,
        *,
        is_error: bool = False,
    ) -> str | list[dict[str, object]]:
        blocks = cls._anthropic_tool_result_content_to_responses_blocks(content)
        if is_error:
            return [{"type": "input_text", "text": "Tool result error"}, *blocks]
        if blocks and all(block.get("type") == "input_text" for block in blocks):
            return "\n".join(
                str(block.get("text", ""))
                for block in blocks
                if str(block.get("text", ""))
            )
        if blocks:
            return blocks
        return OpenAIOAuthBridgeExecutor._flatten_content(content)

    @classmethod
    def _anthropic_tool_result_content_to_responses_blocks(
        cls,
        content: object,
    ) -> list[dict[str, object]]:
        if isinstance(content, list):
            blocks: list[dict[str, object]] = []
            for block in content:
                blocks.extend(cls._anthropic_tool_result_block_to_responses_blocks(block))
            return blocks
        return cls._anthropic_tool_result_block_to_responses_blocks(content)

    @classmethod
    def _anthropic_tool_result_block_to_responses_blocks(
        cls,
        block: object,
    ) -> list[dict[str, object]]:
        if block is None:
            return []
        if isinstance(block, str):
            return [{"type": "input_text", "text": block}] if block else []
        if not isinstance(block, dict):
            return [{"type": "input_text", "text": str(block)}]

        block_type = block.get("type")
        if block_type == "text":
            text = str(block.get("text", ""))
            return [{"type": "input_text", "text": text}] if text else []
        if block_type == "image":
            image_block = cls._anthropic_image_to_responses_output(block)
            if image_block is not None:
                return [image_block]
        if block_type in {"document", "file"}:
            file_block = cls._anthropic_file_to_responses_output(block)
            if file_block is not None:
                return [file_block]

        return [{"type": "input_text", "text": cls._json_dumps_compact(block)}]

    @staticmethod
    def _anthropic_image_to_responses_output(
        block: dict[str, object],
    ) -> dict[str, object] | None:
        output: dict[str, object] = {"type": "input_image"}
        detail = block.get("detail")
        if isinstance(detail, str) and detail:
            output["detail"] = detail

        source = block.get("source")
        if isinstance(source, dict):
            source_type = source.get("type")
            if source_type == "base64":
                media_type = source.get("media_type")
                data = source.get("data")
                if isinstance(media_type, str) and isinstance(data, str) and data:
                    output["image_url"] = f"data:{media_type};base64,{data}"
            elif isinstance(source.get("url"), str):
                output["image_url"] = str(source["url"])
            elif isinstance(source.get("image_url"), str):
                output["image_url"] = str(source["image_url"])
            elif isinstance(source.get("file_id"), str):
                output["file_id"] = str(source["file_id"])

        if "image_url" not in output and isinstance(block.get("image_url"), str):
            output["image_url"] = str(block["image_url"])
        if "image_url" not in output and isinstance(block.get("url"), str):
            output["image_url"] = str(block["url"])
        if "file_id" not in output and isinstance(block.get("file_id"), str):
            output["file_id"] = str(block["file_id"])

        if "image_url" in output or "file_id" in output:
            return output
        return None

    @staticmethod
    def _anthropic_file_to_responses_output(
        block: dict[str, object],
    ) -> dict[str, object] | None:
        output: dict[str, object] = {"type": "input_file"}
        filename = block.get("filename") or block.get("title") or block.get("name")
        if isinstance(filename, str) and filename:
            output["filename"] = filename

        source = block.get("source")
        if isinstance(source, dict):
            source_type = source.get("type")
            if source_type == "base64" and isinstance(source.get("data"), str):
                output["file_data"] = str(source["data"])
            elif isinstance(source.get("url"), str):
                output["file_url"] = str(source["url"])
            elif isinstance(source.get("file_url"), str):
                output["file_url"] = str(source["file_url"])
            elif isinstance(source.get("file_id"), str):
                output["file_id"] = str(source["file_id"])

        if "file_url" not in output and isinstance(block.get("file_url"), str):
            output["file_url"] = str(block["file_url"])
        if "file_url" not in output and isinstance(block.get("url"), str):
            output["file_url"] = str(block["url"])
        if "file_id" not in output and isinstance(block.get("file_id"), str):
            output["file_id"] = str(block["file_id"])
        if "file_data" not in output and isinstance(block.get("file_data"), str):
            output["file_data"] = str(block["file_data"])

        if any(key in output for key in ("file_data", "file_id", "file_url")):
            return output
        return None

    @classmethod
    def _anthropic_tools_to_responses(
        cls,
        tools: object,
        mcp_servers: object = None,
    ) -> list[dict[str, object]]:
        mcp_server_map = cls._anthropic_mcp_server_map(mcp_servers)
        translated: list[dict[str, object]] = []
        used_mcp_servers: set[str] = set()

        if isinstance(tools, list):
            for tool in tools:
                if not isinstance(tool, dict):
                    continue
                tool_type = tool.get("type")
                if tool_type == "mcp_toolset":
                    server_name = tool.get("mcp_server_name") or tool.get("server_name")
                    if isinstance(server_name, str):
                        if server_name in used_mcp_servers:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail=(
                                    "Each Anthropic MCP server must be referenced by "
                                    "exactly one MCP toolset"
                                ),
                            )
                        used_mcp_servers.add(server_name)
                    translated.append(
                        cls._anthropic_mcp_toolset_to_responses(tool, mcp_server_map)
                    )
                    continue
                if tool_type not in {None, "function"}:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unsupported Anthropic tool type for Codex bridge: {tool_type}",
                    )
                name = tool.get("name")
                if not isinstance(name, str) or not name:
                    continue
                translated_tool: dict[str, object] = {
                    "type": "function",
                    "name": name,
                    "parameters": tool.get("input_schema")
                    or {"type": "object", "properties": {}},
                }
                description = tool.get("description")
                if isinstance(description, str) and description:
                    translated_tool["description"] = description
                translated.append(translated_tool)

        unreferenced_servers = sorted(set(mcp_server_map) - used_mcp_servers)
        if unreferenced_servers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Each Anthropic MCP server must be referenced by exactly one "
                    f"MCP toolset: {', '.join(unreferenced_servers)}"
                ),
            )
        return translated

    @classmethod
    def _anthropic_mcp_server_map(
        cls,
        mcp_servers: object,
    ) -> dict[str, dict[str, object]]:
        if not isinstance(mcp_servers, list):
            return {}

        servers: dict[str, dict[str, object]] = {}
        for server in mcp_servers:
            if not isinstance(server, dict):
                continue
            server_type = server.get("type")
            if server_type != "url":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported Anthropic MCP server type for Codex bridge: {server_type}",
                )
            name = server.get("name")
            url = server.get("url")
            if not isinstance(name, str) or not name or not isinstance(url, str) or not url:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Anthropic MCP servers require non-empty name and url",
                )
            servers[name] = server
        return servers

    @classmethod
    def _anthropic_mcp_toolset_to_responses(
        cls,
        toolset: dict[str, object],
        mcp_server_map: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        server_name = toolset.get("mcp_server_name") or toolset.get("server_name")
        if not isinstance(server_name, str) or not server_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Anthropic MCP toolset requires mcp_server_name",
            )
        server = mcp_server_map.get(server_name)
        if server is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Anthropic MCP toolset references unknown server: {server_name}",
            )

        translated = cls._anthropic_mcp_server_to_responses_tool(server)
        allowed_tools = cls._anthropic_mcp_allowed_tools_from_toolset(toolset)
        if allowed_tools is not None:
            translated["allowed_tools"] = allowed_tools

        require_approval = cls._anthropic_mcp_require_approval(toolset.get("require_approval"))
        if require_approval is not None:
            translated["require_approval"] = require_approval
        return translated

    @classmethod
    def _anthropic_mcp_server_to_responses_tool(
        cls,
        server: dict[str, object],
    ) -> dict[str, object]:
        server_name = str(server["name"])
        translated: dict[str, object] = {
            "type": "mcp",
            "server_label": server_name,
            "server_url": str(server["url"]),
        }

        authorization = server.get("authorization_token") or server.get("authorization")
        if isinstance(authorization, str) and authorization:
            translated["authorization"] = authorization

        description = server.get("description") or server.get("server_description")
        if isinstance(description, str) and description:
            translated["server_description"] = description

        tool_configuration = server.get("tool_configuration")
        if isinstance(tool_configuration, dict):
            allowed_tools = tool_configuration.get("allowed_tools")
            if isinstance(allowed_tools, list):
                translated["allowed_tools"] = [
                    str(name) for name in allowed_tools if isinstance(name, str) and name
                ]
            require_approval = cls._anthropic_mcp_require_approval(
                tool_configuration.get("require_approval")
            )
            if require_approval is not None:
                translated["require_approval"] = require_approval
        return translated

    @staticmethod
    def _anthropic_mcp_allowed_tools_from_toolset(
        toolset: dict[str, object],
    ) -> list[str] | dict[str, object] | None:
        direct_allowed_tools = toolset.get("allowed_tools")
        if isinstance(direct_allowed_tools, list):
            return [
                str(name)
                for name in direct_allowed_tools
                if isinstance(name, str) and name
            ]
        if isinstance(direct_allowed_tools, dict):
            return direct_allowed_tools

        default_config = toolset.get("default_config")
        default_enabled = True
        if isinstance(default_config, dict) and default_config.get("enabled") is False:
            default_enabled = False

        configs = toolset.get("configs")
        if not isinstance(configs, dict):
            return [] if not default_enabled else None

        enabled_tools: list[str] = []
        disabled_tools: list[str] = []
        for tool_name, config in configs.items():
            if not isinstance(tool_name, str) or not tool_name:
                continue
            if not isinstance(config, dict):
                continue
            if config.get("enabled") is True:
                enabled_tools.append(tool_name)
            if config.get("enabled") is False:
                disabled_tools.append(tool_name)

        if default_enabled and disabled_tools:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Anthropic MCP toolset denylist is not supported by Codex bridge",
            )
        if not default_enabled:
            return enabled_tools
        return None

    @staticmethod
    def _anthropic_mcp_require_approval(require_approval: object) -> object | None:
        if require_approval is None:
            return None
        if isinstance(require_approval, str):
            if require_approval in {"always", "never"}:
                return require_approval
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported MCP require_approval policy: {require_approval}",
            )
        if isinstance(require_approval, dict):
            return require_approval
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MCP require_approval must be 'always', 'never', or a filter object",
        )

    @staticmethod
    def _json_dumps_compact(value: object) -> str:
        return json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _anthropic_tool_choice_to_responses(tool_choice: object) -> object | None:
        if tool_choice is None:
            return None
        if isinstance(tool_choice, str):
            return tool_choice
        if not isinstance(tool_choice, dict):
            return None

        choice_type = tool_choice.get("type")
        if choice_type == "auto":
            return "auto"
        if choice_type == "none":
            return "none"
        if choice_type == "any":
            return "required"
        if choice_type == "tool":
            name = tool_choice.get("name")
            if isinstance(name, str) and name:
                return {"type": "function", "name": name}
        return None

    @classmethod
    def _responses_output_to_anthropic_content(
        cls,
        payload: dict[str, object],
    ) -> list[dict[str, object]]:
        output = payload.get("output")
        content: list[dict[str, object]] = []
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if item_type == "message":
                    item_content = item.get("content")
                    if isinstance(item_content, list):
                        for block in item_content:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") in {"output_text", "text"}:
                                content.append(
                                    {
                                        "type": "text",
                                        "text": str(block.get("text", "")),
                                    }
                                )
                    continue
                if item_type == "function_call":
                    content.append(
                        {
                            "type": "tool_use",
                            "id": str(item.get("call_id") or item.get("id") or ""),
                            "name": str(item.get("name") or ""),
                            "input": cls._responses_function_arguments_to_anthropic_input(
                                item.get("arguments")
                            ),
                        }
                    )
                    continue
                if item_type == "mcp_call":
                    content.extend(cls._responses_mcp_call_to_anthropic_blocks(item))
                    continue
                if item_type == "mcp_approval_request":
                    content.append(cls._responses_mcp_approval_request_to_anthropic_block(item))
                    continue
                if item_type == "mcp_list_tools":
                    error = item.get("error")
                    if isinstance(error, str) and error:
                        server_label = str(item.get("server_label") or "unknown")
                        content.append(
                            {
                                "type": "text",
                                "text": f"MCP tool listing failed for {server_label}: {error}",
                            }
                        )
                    continue
                if item_type in {"output_text", "text"}:
                    content.append({"type": "text", "text": str(item.get("text", ""))})

        if content:
            return content
        return [{"type": "text", "text": cls._extract_output_text(payload)}]

    @classmethod
    def _responses_mcp_call_to_anthropic_blocks(
        cls,
        item: dict[str, object],
    ) -> list[dict[str, object]]:
        tool_use_id = str(item.get("id") or "")
        blocks: list[dict[str, object]] = [
            {
                "type": "mcp_tool_use",
                "id": tool_use_id,
                "server_name": str(item.get("server_label") or ""),
                "name": str(item.get("name") or ""),
                "input": cls._responses_function_arguments_to_anthropic_input(
                    item.get("arguments")
                ),
            }
        ]
        if "output" in item or "error" in item or item.get("status") == "failed":
            blocks.append(cls._responses_mcp_call_result_to_anthropic_block(item))
        return blocks

    @staticmethod
    def _responses_mcp_call_result_to_anthropic_block(
        item: dict[str, object],
    ) -> dict[str, object]:
        error = item.get("error")
        is_error = isinstance(error, str) and bool(error)
        if is_error:
            text = str(error)
        else:
            output = item.get("output")
            text = OpenAIOAuthBridgeExecutor._flatten_content(output)
        return {
            "type": "mcp_tool_result",
            "tool_use_id": str(item.get("id") or ""),
            "is_error": is_error,
            "content": [{"type": "text", "text": text}],
        }

    @classmethod
    def _responses_mcp_approval_request_to_anthropic_block(
        cls,
        item: dict[str, object],
    ) -> dict[str, object]:
        return {
            "type": "mcp_approval_request",
            "id": str(item.get("id") or ""),
            "server_name": str(item.get("server_label") or ""),
            "name": str(item.get("name") or ""),
            "input": cls._responses_function_arguments_to_anthropic_input(
                item.get("arguments")
            ),
        }

    @classmethod
    def _anthropic_stop_reason_for_content(
        cls,
        payload: dict[str, object],
        content: list[dict[str, object]],
    ) -> str:
        if any(
            isinstance(block, dict)
            and block.get("type") in {"tool_use", "mcp_approval_request"}
            for block in content
        ):
            return "tool_use"
        return cls._finish_reason(payload)

    @staticmethod
    def _responses_function_arguments_to_anthropic_input(arguments: object) -> object:
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except ValueError:
                return {"raw_arguments": arguments}
            return parsed
        return {}

    @staticmethod
    def _extract_output_text(payload: dict[str, object]) -> str:
        if isinstance(payload.get("output_text"), str):
            return str(payload["output_text"])

        output = payload.get("output")
        parts: list[str] = []
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "message":
                    content = item.get("content")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") in {"output_text", "text"}:
                                parts.append(str(block.get("text", "")))
                elif item.get("type") in {"output_text", "text"}:
                    parts.append(str(item.get("text", "")))

        if parts:
            return "\n".join(part for part in parts if part)

        choices = payload.get("choices")
        first_choice = choices[0] if isinstance(choices, list) and choices else {}
        message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
        return OpenAIOAuthBridgeExecutor._flatten_content(message.get("content"))

    @staticmethod
    def _usage_for(payload: dict[str, object]) -> dict[str, int]:
        usage = payload.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        return {
            "input_tokens": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
        }

    @staticmethod
    def _finish_reason(payload: dict[str, object]) -> str:
        choices = payload.get("choices")
        first_choice = choices[0] if isinstance(choices, list) and choices else {}
        if isinstance(first_choice, dict) and isinstance(first_choice.get("finish_reason"), str):
            return str(first_choice["finish_reason"])
        if isinstance(payload.get("status"), str):
            status_value = str(payload["status"])
            if status_value in {"completed", "succeeded"}:
                return "end_turn"
            return status_value
        return "end_turn"


class ClaudeMaxOAuthBridgeExecutor:
    """Proxies Anthropic Messages requests to api.anthropic.com using a Claude Max OAuth token.

    Auth flow:
      1. If the access_token is expired, refresh it first via
         POST https://platform.claude.com/v1/oauth/token with the stored refresh_token.
      2. Use the OAuth access_token directly as a Bearer token with
         anthropic-beta: oauth-2025-04-20 for the /v1/messages call.
    """

    _API_URL = "https://api.anthropic.com/v1/messages"
    _TOKEN_REFRESH_URL = "https://platform.claude.com/v1/oauth/token"
    _OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    _ANTHROPIC_VERSION = "2023-06-01"
    _OAUTH_BETA = "oauth-2025-04-20"
    # Anthropic requires this text to appear in the system prompt for OAuth requests
    # (not an HTTP header — injected as a text string into system content).
    # cc_version mirrors the Claude Code version; cch is hardcoded in that binary.
    _BILLING_HEADER = (
        "x-anthropic-billing-header: cc_version=2.1.87.000;"
        " cc_entrypoint=sdk-cli; cch=00000;"
    )
    _DEFAULT_MAX_TOKENS = 4096

    def execute(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> ExecutionResult:
        access_token = self._ensure_fresh_token(credential)
        anthropic_payload = self._to_anthropic_payload(request)

        headers = self._messages_headers(access_token)
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                self._API_URL,
                headers=headers,
                json=anthropic_payload,
            )

        if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise UpstreamRateLimitError("Claude Max subscription rate limited")
        if is_invalid_credential_status(response.status_code):
            raise UpstreamCredentialInvalidError(self._error_detail(response))
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=self._error_detail(response),
            )

        body = dict(response.json())
        usage = body.get("usage", {})
        result_body = self._from_anthropic_response(body, request.protocol)
        return ExecutionResult(
            body=result_body,
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
        )

    async def stream(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
        extra_headers: dict[str, str] | None = None,
    ) -> AsyncIterator[bytes]:
        access_token = self._ensure_fresh_token(credential)
        payload = self._to_anthropic_payload(request)
        payload["stream"] = True  # ensure streaming is set

        headers = self._messages_headers(access_token, extra=extra_headers)

        async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
            async with client.stream(
                "POST", self._API_URL, headers=headers, json=payload
            ) as response:
                if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    raise UpstreamRateLimitError("Claude Max subscription rate limited")
                if is_invalid_credential_status(response.status_code):
                    body = await response.aread()
                    raise UpstreamCredentialInvalidError(body.decode(errors="replace"))
                if response.status_code >= 400:
                    body = await response.aread()
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=body.decode(errors="replace"),
                    )
                async for chunk in response.aiter_bytes():
                    yield chunk

    def execute_chat_stream(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> Iterator[bytes]:
        access_token = self._ensure_fresh_token(credential)
        payload = self._to_anthropic_payload(request)
        payload["stream"] = True

        headers = self._messages_headers(access_token)
        with httpx.Client(timeout=httpx.Timeout(None)) as client:
            with client.stream("POST", self._API_URL, headers=headers, json=payload) as response:
                if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    raise UpstreamRateLimitError("Claude Max subscription rate limited")
                if is_invalid_credential_status(response.status_code):
                    response.read()
                    raise UpstreamCredentialInvalidError(self._error_detail(response))
                if response.status_code >= 400:
                    response.read()
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=self._error_detail(response),
                    )
                yield from self._anthropic_sse_to_chat_chunks(response.iter_lines())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_message_content(msg: dict) -> dict:  # type: ignore[type-arg]
        """Normalize a single message's content from OpenAI format to Anthropic format."""
        content = msg.get("content")
        if isinstance(content, list):
            normalized = []
            for block in content:
                if not isinstance(block, dict):
                    normalized.append(block)
                    continue
                block_type = block.get("type", "")
                # Map OpenAI content block types → Anthropic types
                if block_type == "input_text":
                    normalized.append({"type": "text", "text": block.get("text", "")})
                elif block_type == "output_text":
                    normalized.append({"type": "text", "text": block.get("text", "")})
                elif block_type == "image_url":
                    url = (block.get("image_url") or {}).get("url", "")
                    if url.startswith("data:"):
                        media_type, data = url.split(";base64,", 1)
                        media_type = media_type.split(":", 1)[1]
                        normalized.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
                    else:
                        normalized.append({"type": "image", "source": {"type": "url", "url": url}})
                else:
                    normalized.append(block)
            return {**msg, "content": normalized}
        return msg

    def _to_anthropic_payload(self, request: UnifiedInferenceRequest) -> dict:  # type: ignore[type-arg]
        """Convert any protocol payload to Anthropic Messages format."""
        protocol = request.protocol
        payload = dict(request.payload)

        if protocol == "anthropic_messages":
            payload["model"] = request.upstream_model
            payload.pop("stream", None)
            result = payload
        elif protocol == "openai_chat":
            messages = list(payload.get("messages") or [])
            # "developer" is the OpenAI o-series equivalent of "system"
            system_roles = {"system", "developer"}
            system_parts = [m.get("content", "") for m in messages if m.get("role") in system_roles]
            chat_messages = []
            for message in messages:
                if message.get("role") in system_roles:
                    continue
                normalized = self._normalize_message_content(message)
                chat_messages.append(
                    {
                        "role": normalized.get("role", "user"),
                        "content": normalized.get("content", ""),
                    }
                )
            result = {  # type: ignore[type-arg]
                "model": request.upstream_model,
                "messages": chat_messages,
            }
            if system_parts:
                result["system"] = "\n\n".join(str(p) for p in system_parts)
            for key in ("max_tokens", "temperature", "top_p"):
                if key in payload:
                    result[key] = payload[key]
            if "stop" in payload:
                result["stop_sequences"] = payload["stop"]
            if "tools" in payload:
                result["tools"] = payload["tools"]
        elif protocol == "openai_responses":
            inp = payload.get("input", "")
            system_roles = {"system", "developer"}
            if isinstance(inp, str):
                chat_messages = [{"role": "user", "content": inp}]
                system_from_input: list[str] = []
            else:
                chat_messages = [self._normalize_message_content(m) for m in (inp or []) if isinstance(m, dict) and m.get("role") not in system_roles]
                system_from_input = [m.get("content", "") for m in (inp or []) if isinstance(m, dict) and m.get("role") in system_roles]
            result = {
                "model": request.upstream_model,
                "messages": chat_messages,
            }
            instructions = payload.get("instructions") or (system_from_input[0] if not isinstance(inp, str) and system_from_input else None)
            if instructions:
                result["system"] = str(instructions)
            max_out = payload.get("max_output_tokens")
            if max_out:
                result["max_tokens"] = int(max_out)
            if "temperature" in payload:
                result["temperature"] = payload["temperature"]
        else:
            # Unknown protocol — pass through and let Anthropic reject
            payload["model"] = request.upstream_model
            payload.pop("stream", None)
            result = payload

        if result.get("max_tokens") in (None, ""):
            result["max_tokens"] = self._DEFAULT_MAX_TOKENS
        if result.get("temperature") is not None and result.get("top_p") is not None:
            result.pop("top_p", None)

        # Anthropic requires x-anthropic-billing-header in the system prompt for OAuth requests.
        # Only inject if not already present (Claude Code client injects it itself).
        existing_system = str(result.get("system", ""))
        if "x-anthropic-billing-header" not in existing_system:
            result["system"] = (
                self._BILLING_HEADER + ("\n\n" + existing_system if existing_system else "")
            )

        return result

    def _from_anthropic_response(self, body: dict, protocol: str) -> dict:  # type: ignore[type-arg]
        """Convert Anthropic Messages response back to the requested protocol format."""
        if protocol == "anthropic_messages":
            return body

        # Extract text content from Anthropic response
        content_blocks = body.get("content") or []
        text = "".join(
            block.get("text", "") for block in content_blocks if block.get("type") == "text"
        )
        stop_reason = body.get("stop_reason", "end_turn")
        finish_reason = "stop" if stop_reason in ("end_turn", "stop_sequence") else stop_reason
        usage = body.get("usage", {})

        if protocol == "openai_chat":
            return {
                "id": body.get("id", ""),
                "object": "chat.completion",
                "model": body.get("model", ""),
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": finish_reason,
                }],
                "usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                },
            }

        if protocol == "openai_responses":
            return {
                "id": body.get("id", ""),
                "object": "response",
                "model": body.get("model", ""),
                "output": [{
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }],
                "usage": {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                },
                "status": "completed",
            }

        return body

    @staticmethod
    def _anthropic_sse_to_chat_chunks(lines: object) -> Iterator[bytes]:
        current_event: str | None = None
        current_data: list[str] = []
        message_id = "chatcmpl_claude_max"
        model: str | None = None
        role_emitted = False
        done_emitted = False

        def finish_reason_for(stop_reason: object) -> str:
            if stop_reason in {"end_turn", "stop_sequence"}:
                return "stop"
            return str(stop_reason or "stop")

        def encode_chunk(
            *,
            delta: dict[str, object],
            finish_reason: str | None = None,
        ) -> bytes:
            chunk = {
                "id": message_id,
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish_reason,
                    }
                ],
            }
            return f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n".encode("utf-8")

        def finalize_event() -> list[bytes]:
            nonlocal current_event, current_data, message_id, model, role_emitted, done_emitted
            if not current_data:
                current_event = None
                return []

            raw_data = "\n".join(current_data).strip()
            current_event_name = current_event or "message"
            current_event = None
            current_data = []

            payload = json.loads(raw_data)
            emitted: list[bytes] = []

            if current_event_name == "error" and isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    detail = str(error["message"])
                else:
                    detail = "Upstream request failed"
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)

            if current_event_name == "message_start" and isinstance(payload, dict):
                message = payload.get("message")
                if isinstance(message, dict):
                    message_id = str(message.get("id") or message_id)
                    if isinstance(message.get("model"), str):
                        model = str(message["model"])
                    if not role_emitted and message.get("role") == "assistant":
                        emitted.append(encode_chunk(delta={"role": "assistant"}))
                        role_emitted = True

            if current_event_name == "content_block_delta" and isinstance(payload, dict):
                delta = payload.get("delta")
                if isinstance(delta, dict) and delta.get("type") == "text_delta":
                    text = delta.get("text")
                    if isinstance(text, str) and text:
                        emitted.append(encode_chunk(delta={"content": text}))

            if current_event_name == "message_delta" and isinstance(payload, dict):
                delta = payload.get("delta")
                stop_reason = delta.get("stop_reason") if isinstance(delta, dict) else None
                if stop_reason is not None:
                    emitted.append(
                        encode_chunk(delta={}, finish_reason=finish_reason_for(stop_reason))
                    )

            if current_event_name == "message_stop" and not done_emitted:
                emitted.append(b"data: [DONE]\n\n")
                done_emitted = True

            return emitted

        for raw_line in lines:
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
            if not line:
                for chunk in finalize_event():
                    yield chunk
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                current_event = line.partition(":")[2].strip()
                continue
            if line.startswith("data:"):
                current_data.append(line.partition(":")[2].lstrip())

        for chunk in finalize_event():
            yield chunk
        if not done_emitted:
            yield b"data: [DONE]\n\n"

    def _ensure_fresh_token(self, credential: ProviderCredential) -> str:
        """Return a valid OAuth access_token, refreshing via refresh_token if expired."""
        from datetime import datetime, timezone
        expires_at = credential.expires_at
        if expires_at:
            if isinstance(expires_at, str):
                from dateutil import parser as dp
                expires_at = dp.parse(expires_at)
            now = datetime.now(tz=timezone.utc)
            if now >= expires_at:
                _log.info("claude-max token expired at %s, refreshing", expires_at)
                return self._refresh_token(credential)
        return str(credential.access_token or "")

    def _refresh_token(self, credential: ProviderCredential) -> str:
        """Call the OAuth token refresh endpoint and return the new access_token."""
        refresh_token = credential.refresh_token
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Claude Max OAuth token expired and no refresh token is available. "
                    "Run 'routerctl claude bind' again."
                ),
            )
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                self._TOKEN_REFRESH_URL,
                content=urlencode(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": self._OAUTH_CLIENT_ID,
                    }
                ),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
                },
            )
        if response.status_code in {
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        }:
            raise UpstreamCredentialInvalidError(
                (
                    f"Claude Max token refresh failed ({response.status_code}): {response.text[:200]}. "
                    "Run 'routerctl claude bind' again."
                )
            )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"Claude Max token refresh failed ({response.status_code}): {response.text[:200]}. "
                    "Run 'routerctl claude bind' again."
                ),
            )
        return str(response.json().get("access_token", ""))

    def _messages_headers(self, access_token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "anthropic-version": self._ANTHROPIC_VERSION,
            "anthropic-beta": self._OAUTH_BETA,
            # Required by Anthropic for OAuth — client identity headers
            "user-agent": "claude-code/2.1.87",
            "anthropic-client-name": "claude-code",
            "anthropic-client-version": "2.1.87",
        }
        if extra:
            headers.update(extra)
            # Re-merge anthropic-beta so caller's betas are kept alongside ours
            upstream_betas = {b.strip() for b in headers.get("anthropic-beta", "").split(",") if b.strip()}
            upstream_betas.add(self._OAUTH_BETA)
            headers["anthropic-beta"] = ",".join(sorted(upstream_betas))
        return headers

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return str(error["message"])
        return "Upstream request failed"


class OAuthBridgeExecutorRouter:
    def __init__(self, settings: AppSettings) -> None:
        self._openai = OpenAIOAuthBridgeExecutor(settings)
        self._openai_codex = OpenAICodexOAuthBridgeExecutor(settings)
        self._claude_max = ClaudeMaxOAuthBridgeExecutor()
        self._missing = MissingExecutor("OAuth bridge")

    def execute(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> ExecutionResult:
        if request.provider == "openai-codex" or credential.provider == "openai-codex":
            return self._openai_codex.execute(request, credential)
        if request.provider == "openai" or credential.provider == "openai":
            return self._openai.execute(request, credential)
        if credential.provider == "claude-max":
            return self._claude_max.execute(request, credential)
        return self._missing.execute(request, credential)

    async def stream_claude_max(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
        extra_headers: dict[str, str] | None = None,
    ) -> AsyncIterator[bytes]:
        async for chunk in self._claude_max.stream(request, credential, extra_headers):
            yield chunk

    def stream_openai_codex(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> Iterator[bytes]:
        yield from self._openai_codex.execute_stream(request, credential)

    def stream_claude_chat(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> Iterator[bytes]:
        yield from self._claude_max.execute_chat_stream(request, credential)
