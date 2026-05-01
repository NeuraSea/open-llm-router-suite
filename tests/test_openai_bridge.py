import json

import httpx
import pytest
from fastapi import HTTPException

from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.domain.credentials import CredentialState, CredentialVisibility, ProviderCredential
from enterprise_llm_proxy.domain.inference import UnifiedInferenceRequest
from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.services.openai_bridge import (
    ClaudeMaxOAuthBridgeExecutor,
    OpenAICodexOAuthBridgeExecutor,
)
from enterprise_llm_proxy.services.execution import UpstreamCredentialInvalidError


def test_codex_bridge_proxy_transport_builds_httpx_compatible_client_kwargs(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("HTTP_PROXY", "http://host.docker.internal:8118")
    monkeypatch.setenv("HTTPS_PROXY", "http://host.docker.internal:8118")

    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(
            openai_codex_api_base_url="https://chatgpt.com/backend-api",
            openai_codex_transport="proxy",
        )
    )
    client_kwargs = executor._client_kwargs()  # type: ignore[attr-defined]

    assert client_kwargs["trust_env"] is False
    assert client_kwargs["proxy"] == "http://host.docker.internal:8118"
    assert "proxies" not in client_kwargs
    with httpx.Client(**client_kwargs):
        pass


def test_codex_bridge_uses_backend_api_responses_endpoint() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_123",
        protocol="openai_responses",
        model="openai-codex/gpt-5-codex",
        model_profile="openai-codex/gpt-5-codex",
        upstream_model="gpt-5-codex",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "gpt-5-codex",
            "input": "Say hello",
            "max_output_tokens": 128,
            "temperature": 0.2,
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=128,
    )

    payload, endpoint = executor._build_request(request)  # type: ignore[attr-defined]

    assert endpoint == "/codex/responses"
    assert executor._url_for(endpoint) == "https://chatgpt.com/backend-api/codex/responses"  # type: ignore[attr-defined]
    assert payload["model"] == "gpt-5-codex"
    assert payload["store"] is False
    assert payload["stream"] is True
    assert payload["instructions"] == ""
    assert payload["input"] == "Say hello"
    assert "transport" not in payload
    assert "max_output_tokens" not in payload
    assert "temperature" not in payload


def test_codex_bridge_translates_anthropic_messages_to_responses_payload() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_123",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5-codex",
        model_profile="openai-codex/gpt-5-codex",
        upstream_model="gpt-5-codex",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "gpt-5-codex",
            "system": "You are helpful",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Say hello"}]}
            ],
            "max_tokens": 64,
            "temperature": 0.7,
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=64,
    )

    payload, endpoint = executor._build_request(request)  # type: ignore[attr-defined]

    assert endpoint == "/codex/responses"
    assert payload["model"] == "gpt-5-codex"
    assert payload["store"] is False
    assert payload["stream"] is True
    assert payload["instructions"] == "You are helpful"
    assert "max_output_tokens" not in payload
    assert "transport" not in payload
    assert "temperature" not in payload
    assert payload["input"] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "Say hello"}],
        }
    ]


def test_codex_bridge_defaults_empty_instructions_for_anthropic_messages() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_123",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5-codex",
        model_profile="openai-codex/gpt-5-codex",
        upstream_model="gpt-5-codex",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "gpt-5-codex",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Say hello"}]}
            ],
            "max_tokens": 64,
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=64,
    )

    payload, _endpoint = executor._build_request(request)  # type: ignore[attr-defined]

    assert payload["instructions"] == ""


def test_codex_bridge_translates_openai_chat_using_upstream_model_name() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_789",
        protocol="openai_chat",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 16,
            "temperature": 0.8,
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=16,
    )

    payload, endpoint = executor._build_request(request)  # type: ignore[attr-defined]

    assert endpoint == "/codex/responses"
    assert payload["model"] == "gpt-5.4"
    assert "temperature" not in payload


def test_codex_bridge_translates_anthropic_messages_using_upstream_model_name() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_790",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Say hello"}]}],
            "temperature": 0.8,
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=16,
    )

    payload, endpoint = executor._build_request(request)  # type: ignore[attr-defined]

    assert endpoint == "/codex/responses"
    assert payload["model"] == "gpt-5.4"
    assert "temperature" not in payload


def test_codex_bridge_translates_assistant_history_to_output_text_blocks() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_456",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5-codex",
        model_profile="openai-codex/gpt-5-codex",
        upstream_model="gpt-5-codex",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "gpt-5-codex",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "你好"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "你好！"}]},
                {"role": "user", "content": [{"type": "text", "text": "你是什么模型"}]},
            ],
            "max_tokens": 64,
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=64,
    )

    payload, _endpoint = executor._build_request(request)  # type: ignore[attr-defined]

    assert payload["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "你好"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "你好！"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "你是什么模型"}]},
    ]


def test_codex_bridge_parses_sse_completed_event() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    payload = executor._parse_sse_payload(  # type: ignore[attr-defined]
        [
            'event: response.created',
            'data: {"type":"response.created","response":{"id":"resp_1","status":"in_progress"}}',
            "",
            'event: response.completed',
            'data: {"type":"response.completed","response":{"id":"resp_1","status":"completed","model":"gpt-5.1-codex","output":[{"id":"msg_1","type":"message","status":"completed","role":"assistant","content":[{"type":"output_text","text":"smoke-ok"}]}],"usage":{"input_tokens":12,"output_tokens":67}}}',
            "",
        ]
    )

    assert payload["id"] == "resp_1"
    assert payload["status"] == "completed"
    assert payload["usage"] == {"input_tokens": 12, "output_tokens": 67}


def test_codex_bridge_preserves_output_text_from_output_item_done_events() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    payload = executor._parse_sse_payload(  # type: ignore[attr-defined]
        [
            'event: response.created',
            'data: {"type":"response.created","response":{"id":"resp_2","status":"in_progress","output":[]}}',
            "",
            'event: response.output_item.done',
            'data: {"type":"response.output_item.done","item":{"id":"msg_1","type":"message","status":"completed","role":"assistant","content":[{"type":"output_text","text":"Hello!"}]},"output_index":0}',
            "",
            'event: response.completed',
            'data: {"type":"response.completed","response":{"id":"resp_2","status":"completed","model":"gpt-5.4","output":[],"usage":{"input_tokens":12,"output_tokens":6}}}',
            "",
        ]
    )

    translated = executor._translate_responses_to_chat(payload)  # type: ignore[attr-defined]

    assert translated["choices"][0]["message"]["content"] == "Hello!"


def test_codex_bridge_retries_once_after_unsupported_parameter_response(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                content=(
                    "event: response.failed\n"
                    "data: {\"type\":\"response.failed\",\"error\":{\"message\":"
                    "\"Unsupported parameter: 'foo'\"}}\n\n"
                ),
                headers={"Content-Type": "text/event-stream"},
            )
        return httpx.Response(
            200,
            content=(
                "event: response.completed\n"
                "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_retry_ok\","
                "\"status\":\"completed\",\"model\":\"gpt-5.4\",\"output\":[],\"usage\":"
                "{\"input_tokens\":3,\"output_tokens\":2}}}\n\n"
            ),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )
    monkeypatch.setattr(
        executor,
        "_client_kwargs",
        lambda: {"timeout": 30.0, "transport": transport},
    )
    request = UnifiedInferenceRequest(
        request_id="req_retry_param",
        protocol="openai_responses",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "input": "Say hello",
            "foo": "bar",
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=8,
    )
    credential = ProviderCredential(
        id="cred-codex",
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-codex",
        scopes=["model:read"],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token="access-token",
        refresh_token=None,
        owner_principal_id=None,
        visibility=CredentialVisibility.ENTERPRISE_POOL,
        source="admin",
    )

    result = executor.execute(request, credential)
    cached_payload, _endpoint = executor._build_request(request)  # type: ignore[attr-defined]

    assert result.body["id"] == "resp_retry_ok"
    assert len(requests) == 2
    assert requests[0]["foo"] == "bar"
    assert "foo" not in requests[1]
    assert "foo" not in cached_payload


def test_codex_bridge_stream_retries_once_after_unsupported_parameter_response(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                content=(
                    "event: response.failed\n"
                    "data: {\"type\":\"response.failed\",\"error\":{\"message\":"
                    "\"Unknown parameter: bar\"}}\n\n"
                ),
                headers={"Content-Type": "text/event-stream"},
            )
        return httpx.Response(
            200,
            content=(
                "event: response.completed\n"
                "data: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_stream_ok\","
                "\"status\":\"completed\",\"model\":\"gpt-5.4\",\"output\":[],\"usage\":"
                "{\"input_tokens\":3,\"output_tokens\":2}}}\n\n"
            ),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )
    monkeypatch.setattr(
        executor,
        "_client_kwargs",
        lambda: {"timeout": 30.0, "transport": transport},
    )
    request = UnifiedInferenceRequest(
        request_id="req_retry_stream_param",
        protocol="openai_responses",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "input": "Say hello",
            "bar": "baz",
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=8,
    )
    credential = ProviderCredential(
        id="cred-codex",
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-codex",
        scopes=["model:read"],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token="access-token",
        refresh_token=None,
        owner_principal_id=None,
        visibility=CredentialVisibility.ENTERPRISE_POOL,
        source="admin",
    )

    chunks = list(executor.execute_stream(request, credential))

    assert len(requests) == 2
    assert requests[0]["bar"] == "baz"
    assert "bar" not in requests[1]
    assert any(b"resp_stream_ok" in chunk for chunk in chunks)


def test_codex_bridge_stream_translates_output_text_delta_events_to_chat_chunks() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    chunks = list(
        executor._responses_sse_to_chat_chunks(  # type: ignore[attr-defined]
            [
                'event: response.created',
                'data: {"type":"response.created","response":{"id":"resp_3","model":"gpt-5.4","status":"in_progress"}}',
                "",
                'event: response.output_item.added',
                'data: {"type":"response.output_item.added","item":{"id":"msg_3","type":"message","status":"in_progress","content":[],"role":"assistant"},"output_index":0}',
                "",
                'event: response.output_text.delta',
                'data: {"type":"response.output_text.delta","delta":"Hello","item_id":"msg_3","output_index":0}',
                "",
                'event: response.output_text.delta',
                'data: {"type":"response.output_text.delta","delta":"!","item_id":"msg_3","output_index":0}',
                "",
                'event: response.completed',
                'data: {"type":"response.completed","response":{"id":"resp_3","model":"gpt-5.4","status":"completed","usage":{"input_tokens":11,"output_tokens":6}}}',
                "",
            ]
        )
    )

    assert b'"delta":{"role":"assistant"}' in chunks[0]
    assert b'"delta":{"content":"Hello"}' in chunks[1]
    assert b'"delta":{"content":"!"}' in chunks[2]
    assert b'"finish_reason":"end_turn"' in chunks[3]
    assert chunks[4] == b"data: [DONE]\n\n"


def test_codex_bridge_translates_anthropic_tool_use_and_results_to_responses_payload() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_tool_bridge",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "tools": [
                {
                    "name": "run_shell",
                    "description": "Run a shell command",
                    "input_schema": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                        "required": ["command"],
                    },
                }
            ],
            "tool_choice": {"type": "tool", "name": "run_shell"},
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "List the files"}]},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "run_shell",
                            "input": {"command": "ls"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "README.md\nsrc",
                        },
                        {"type": "text", "text": "What should I inspect next?"},
                    ],
                },
            ],
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=32,
    )

    payload, endpoint = executor._build_request(request)  # type: ignore[attr-defined]

    assert endpoint == "/codex/responses"
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "run_shell",
            "description": "Run a shell command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        }
    ]
    assert payload["tool_choice"] == {"type": "function", "name": "run_shell"}
    assert payload["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "List the files"}]},
        {
            "type": "function_call",
            "call_id": "toolu_1",
            "name": "run_shell",
            "arguments": '{"command":"ls"}',
        },
        {
            "type": "function_call_output",
            "call_id": "toolu_1",
            "output": "README.md\nsrc",
        },
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "What should I inspect next?"}],
        },
    ]


def test_codex_bridge_preserves_structured_tool_result_content_for_responses() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_structured_tool_result",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_structured",
                            "is_error": True,
                            "content": [
                                {"type": "text", "text": "Screenshot capture failed"},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": "iVBORw0KGgo=",
                                    },
                                },
                                {
                                    "type": "document",
                                    "title": "trace.txt",
                                    "source": {
                                        "type": "url",
                                        "url": "https://example.test/trace.txt",
                                    },
                                },
                            ],
                        }
                    ],
                }
            ],
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=32,
    )

    payload, _endpoint = executor._build_request(request)  # type: ignore[attr-defined]

    assert payload["input"] == [
        {
            "type": "function_call_output",
            "call_id": "toolu_structured",
            "output": [
                {"type": "input_text", "text": "Tool result error"},
                {"type": "input_text", "text": "Screenshot capture failed"},
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,iVBORw0KGgo=",
                },
                {
                    "type": "input_file",
                    "file_url": "https://example.test/trace.txt",
                    "filename": "trace.txt",
                },
            ],
        }
    ]


def test_codex_bridge_rejects_unsupported_anthropic_tool_types() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_unsupported_tool",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "tools": [{"type": "web_search_20250305", "name": "web_search"}],
            "messages": [{"role": "user", "content": "Search the web"}],
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=32,
    )

    with pytest.raises(HTTPException, match="Unsupported Anthropic tool type"):
        executor._build_request(request)  # type: ignore[attr-defined]


def test_codex_bridge_translates_anthropic_mcp_toolset_to_responses_tool() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_mcp_toolset",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "mcp_servers": [
                {
                    "type": "url",
                    "name": "github",
                    "url": "https://mcp.example.test/sse",
                    "authorization_token": "mcp-token",
                }
            ],
            "tools": [
                {
                    "type": "mcp_toolset",
                    "mcp_server_name": "github",
                    "default_config": {"enabled": False},
                    "configs": {
                        "get_issue": {"enabled": True},
                        "list_repos": {"enabled": True},
                    },
                    "require_approval": "never",
                }
            ],
            "messages": [{"role": "user", "content": "Use GitHub"}],
            "temperature": 0.4,
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=32,
    )

    payload, _endpoint = executor._build_request(request)  # type: ignore[attr-defined]

    assert "temperature" not in payload
    assert payload["tools"] == [
        {
            "type": "mcp",
            "server_label": "github",
            "server_url": "https://mcp.example.test/sse",
            "authorization": "mcp-token",
            "allowed_tools": ["get_issue", "list_repos"],
            "require_approval": "never",
        }
    ]


def test_codex_bridge_rejects_anthropic_mcp_toolset_denylist() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_mcp_denylist",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "mcp_servers": [
                {
                    "type": "url",
                    "name": "github",
                    "url": "https://mcp.example.test/sse",
                }
            ],
            "tools": [
                {
                    "type": "mcp_toolset",
                    "mcp_server_name": "github",
                    "default_config": {"enabled": True},
                    "configs": {"delete_repo": {"enabled": False}},
                }
            ],
            "messages": [{"role": "user", "content": "Use GitHub"}],
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=32,
    )

    with pytest.raises(HTTPException, match="denylist"):
        executor._build_request(request)  # type: ignore[attr-defined]


def test_codex_bridge_rejects_unreferenced_anthropic_mcp_servers() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_mcp_unreferenced",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "mcp_servers": [
                {
                    "type": "url",
                    "name": "github",
                    "url": "https://mcp.example.test/github/sse",
                },
                {
                    "type": "url",
                    "name": "prod-admin",
                    "url": "https://mcp.example.test/admin/sse",
                },
            ],
            "tools": [
                {
                    "type": "mcp_toolset",
                    "mcp_server_name": "github",
                    "default_config": {"enabled": False},
                    "configs": {"get_issue": {"enabled": True}},
                }
            ],
            "messages": [{"role": "user", "content": "Use GitHub"}],
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=32,
    )

    with pytest.raises(HTTPException, match="exactly one MCP toolset"):
        executor._build_request(request)  # type: ignore[attr-defined]


def test_codex_bridge_rejects_duplicate_anthropic_mcp_toolsets() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_mcp_duplicate_toolset",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "mcp_servers": [
                {
                    "type": "url",
                    "name": "github",
                    "url": "https://mcp.example.test/github/sse",
                }
            ],
            "tools": [
                {
                    "type": "mcp_toolset",
                    "mcp_server_name": "github",
                    "default_config": {"enabled": False},
                    "configs": {"get_issue": {"enabled": True}},
                },
                {
                    "type": "mcp_toolset",
                    "mcp_server_name": "github",
                    "default_config": {"enabled": False},
                    "configs": {"list_repos": {"enabled": True}},
                },
            ],
            "messages": [{"role": "user", "content": "Use GitHub"}],
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=32,
    )

    with pytest.raises(HTTPException, match="exactly one MCP toolset"):
        executor._build_request(request)  # type: ignore[attr-defined]


def test_codex_bridge_translates_anthropic_mcp_history_to_responses_items() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    request = UnifiedInferenceRequest(
        request_id="req_mcp_history",
        protocol="anthropic_messages",
        model="openai-codex/gpt-5.4",
        model_profile="openai-codex/gpt-5.4",
        upstream_model="gpt-5.4",
        auth_modes=["codex_chatgpt_oauth_imported"],
        provider="openai-codex",
        payload={
            "model": "openai-codex/gpt-5.4",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "mcp_tool_use",
                            "id": "mcptoolu_1",
                            "server_name": "github",
                            "name": "get_issue",
                            "input": {"number": 7},
                        },
                        {
                            "type": "mcp_tool_result",
                            "tool_use_id": "mcptoolu_1",
                            "is_error": False,
                            "content": [{"type": "text", "text": "Issue body"}],
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "mcp_approval_response",
                            "approval_request_id": "approval_1",
                            "approve": True,
                            "reason": "User approved",
                        }
                    ],
                },
            ],
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=32,
    )

    payload, _endpoint = executor._build_request(request)  # type: ignore[attr-defined]

    assert payload["input"] == [
        {
            "type": "mcp_call",
            "id": "mcptoolu_1",
            "server_label": "github",
            "name": "get_issue",
            "arguments": '{"number":7}',
            "output": "Issue body",
            "status": "completed",
        },
        {
            "type": "mcp_approval_response",
            "approval_request_id": "approval_1",
            "approve": True,
            "reason": "User approved",
        },
    ]


def test_codex_bridge_translates_responses_mcp_call_to_anthropic_blocks() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    translated = executor._translate_responses_to_anthropic(  # type: ignore[attr-defined]
        {
            "id": "resp_mcp",
            "model": "gpt-5.4",
            "status": "completed",
            "output": [
                {
                    "type": "mcp_call",
                    "id": "mcp_1",
                    "server_label": "github",
                    "name": "get_issue",
                    "arguments": '{"number":7}',
                    "output": "Issue body",
                    "status": "completed",
                }
            ],
            "usage": {"input_tokens": 12, "output_tokens": 8},
        }
    )

    assert translated["content"] == [
        {
            "type": "mcp_tool_use",
            "id": "mcp_1",
            "server_name": "github",
            "name": "get_issue",
            "input": {"number": 7},
        },
        {
            "type": "mcp_tool_result",
            "tool_use_id": "mcp_1",
            "is_error": False,
            "content": [{"type": "text", "text": "Issue body"}],
        },
    ]
    assert translated["stop_reason"] == "end_turn"


def test_codex_bridge_translates_responses_mcp_approval_request_to_anthropic_block() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    translated = executor._translate_responses_to_anthropic(  # type: ignore[attr-defined]
        {
            "id": "resp_mcp_approval",
            "model": "gpt-5.4",
            "status": "completed",
            "output": [
                {
                    "type": "mcp_approval_request",
                    "id": "approval_1",
                    "server_label": "github",
                    "name": "delete_repo",
                    "arguments": '{"repo":"danger"}',
                }
            ],
        }
    )

    assert translated["content"] == [
        {
            "type": "mcp_approval_request",
            "id": "approval_1",
            "server_name": "github",
            "name": "delete_repo",
            "input": {"repo": "danger"},
        }
    ]
    assert translated["stop_reason"] == "tool_use"


def test_codex_bridge_stream_translates_mcp_call_and_approval_events_to_anthropic_sse() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    chunks = list(
        executor._responses_sse_to_anthropic_events(  # type: ignore[attr-defined]
            [
                "event: response.created",
                'data: {"type":"response.created","response":{"id":"resp_mcp_stream","model":"gpt-5.4","status":"in_progress"}}',
                "",
                "event: response.output_item.added",
                'data: {"type":"response.output_item.added","item":{"id":"mcp_1","type":"mcp_call","server_label":"github","name":"get_issue","arguments":"","status":"in_progress"},"output_index":0}',
                "",
                "event: response.mcp_call_arguments.delta",
                'data: {"type":"response.mcp_call_arguments.delta","output_index":0,"delta":"{\\"number\\":"}',
                "",
                "event: response.mcp_call_arguments.delta",
                'data: {"type":"response.mcp_call_arguments.delta","output_index":0,"delta":"7}"}',
                "",
                "event: response.output_item.done",
                'data: {"type":"response.output_item.done","item":{"id":"mcp_1","type":"mcp_call","server_label":"github","name":"get_issue","arguments":"{\\"number\\":7}","output":"Issue body","status":"completed"},"output_index":0}',
                "",
                "event: response.output_item.done",
                'data: {"type":"response.output_item.done","item":{"id":"approval_1","type":"mcp_approval_request","server_label":"github","name":"delete_repo","arguments":"{\\"repo\\":\\"danger\\"}"},"output_index":1}',
                "",
                "event: response.completed",
                'data: {"type":"response.completed","response":{"id":"resp_mcp_stream","model":"gpt-5.4","status":"completed","usage":{"input_tokens":11,"output_tokens":6}}}',
                "",
            ]
        )
    )

    body = b"".join(chunks)

    assert b'"type":"mcp_tool_use"' in body
    assert b'"server_name":"github"' in body
    assert b'"type":"input_json_delta"' in body
    assert b'"partial_json":"{\\"number\\":"}' in body
    assert b'"partial_json":"7}"}' in body
    assert b'"type":"mcp_tool_result"' in body
    assert b'"text":"Issue body"' in body
    assert b'"type":"mcp_approval_request"' in body
    assert b'"stop_reason":"tool_use"' in body


def test_codex_bridge_stream_translates_mcp_call_failed_event_to_anthropic_result() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    chunks = list(
        executor._responses_sse_to_anthropic_events(  # type: ignore[attr-defined]
            [
                "event: response.created",
                'data: {"type":"response.created","response":{"id":"resp_mcp_failed","model":"gpt-5.4","status":"in_progress"}}',
                "",
                "event: response.output_item.added",
                'data: {"type":"response.output_item.added","item":{"id":"mcp_1","type":"mcp_call","server_label":"github","name":"get_issue","arguments":"","status":"in_progress"},"output_index":0}',
                "",
                "event: response.mcp_call_arguments.delta",
                'data: {"type":"response.mcp_call_arguments.delta","output_index":0,"delta":"{\\"number\\":7}"}',
                "",
                "event: response.mcp_call.failed",
                'data: {"type":"response.mcp_call.failed","item":{"id":"mcp_1","type":"mcp_call","server_label":"github","name":"get_issue","arguments":"{\\"number\\":7}","error":"permission denied","status":"failed"},"output_index":0}',
                "",
                "event: response.completed",
                'data: {"type":"response.completed","response":{"id":"resp_mcp_failed","model":"gpt-5.4","status":"completed","usage":{"input_tokens":11,"output_tokens":6}}}',
                "",
            ]
        )
    )

    body = b"".join(chunks)

    assert b'"type":"mcp_tool_use"' in body
    assert b'"type":"mcp_tool_result"' in body
    assert b'"is_error":true' in body
    assert b'"text":"permission denied"' in body
    assert b'"stop_reason":"end_turn"' in body


def test_codex_bridge_parse_sse_payload_preserves_mcp_call_failed_event() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    payload = executor._parse_sse_payload(  # type: ignore[attr-defined]
        [
            "event: response.created",
            'data: {"type":"response.created","response":{"id":"resp_mcp_failed","model":"gpt-5.4","status":"in_progress"}}',
            "",
            "event: response.output_item.added",
            'data: {"type":"response.output_item.added","item":{"id":"mcp_1","type":"mcp_call","server_label":"github","name":"get_issue","arguments":"","status":"in_progress"},"output_index":0}',
            "",
            "event: response.mcp_call.failed",
            'data: {"type":"response.mcp_call.failed","item":{"id":"mcp_1","type":"mcp_call","server_label":"github","name":"get_issue","arguments":"{\\"number\\":7}","error":"permission denied","status":"failed"},"output_index":0}',
            "",
            "event: response.completed",
            'data: {"type":"response.completed","response":{"id":"resp_mcp_failed","model":"gpt-5.4","status":"completed","usage":{"input_tokens":11,"output_tokens":6}}}',
            "",
        ]
    )

    translated = executor._translate_responses_to_anthropic(payload)  # type: ignore[attr-defined]

    assert translated["content"] == [
        {
            "type": "mcp_tool_use",
            "id": "mcp_1",
            "server_name": "github",
            "name": "get_issue",
            "input": {"number": 7},
        },
        {
            "type": "mcp_tool_result",
            "tool_use_id": "mcp_1",
            "is_error": True,
            "content": [{"type": "text", "text": "permission denied"}],
        },
    ]
    assert translated["stop_reason"] == "end_turn"


def test_codex_bridge_translates_responses_function_calls_to_anthropic_tool_use() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    translated = executor._translate_responses_to_anthropic(  # type: ignore[attr-defined]
        {
            "id": "resp_tool_use",
            "model": "gpt-5.4",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "I checked the workspace."}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "run_shell",
                    "arguments": '{"command":"ls -la"}',
                },
            ],
            "usage": {"input_tokens": 12, "output_tokens": 7},
        }
    )

    assert translated["content"] == [
        {"type": "text", "text": "I checked the workspace."},
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "run_shell",
            "input": {"command": "ls -la"},
        },
    ]
    assert translated["stop_reason"] == "tool_use"
    assert translated["usage"] == {"input_tokens": 12, "output_tokens": 7}


def test_codex_bridge_parses_function_call_output_items_from_sse_before_anthropic_translation() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    payload = executor._parse_sse_payload(  # type: ignore[attr-defined]
        [
            'event: response.created',
            'data: {"type":"response.created","response":{"id":"resp_tool_sse","status":"in_progress","output":[]}}',
            "",
            'event: response.output_item.done',
            'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"call_1","name":"run_shell","arguments":"{\\"command\\":\\"pwd\\"}"},"output_index":0}',
            "",
            'event: response.output_item.done',
            'data: {"type":"response.output_item.done","item":{"type":"function_call","call_id":"call_2","name":"read_file","arguments":"{\\"path\\":\\"README.md\\"}"},"output_index":1}',
            "",
            'event: response.completed',
            'data: {"type":"response.completed","response":{"id":"resp_tool_sse","status":"completed","model":"gpt-5.4","output":[],"usage":{"input_tokens":10,"output_tokens":4}}}',
            "",
        ]
    )

    translated = executor._translate_responses_to_anthropic(payload)  # type: ignore[attr-defined]

    assert [item["type"] for item in payload["output"]] == ["function_call", "function_call"]
    assert [item["call_id"] for item in payload["output"]] == ["call_1", "call_2"]
    assert translated["content"] == [
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "run_shell",
            "input": {"command": "pwd"},
        },
        {
            "type": "tool_use",
            "id": "call_2",
            "name": "read_file",
            "input": {"path": "README.md"},
        },
    ]
    assert translated["stop_reason"] == "tool_use"


def test_codex_bridge_stream_translates_function_call_events_to_anthropic_sse() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    chunks = list(
        executor._responses_sse_to_anthropic_events(  # type: ignore[attr-defined]
            [
                'event: response.created',
                'data: {"type":"response.created","response":{"id":"resp_tool_stream","model":"gpt-5.4","status":"in_progress"}}',
                "",
                'event: response.output_item.added',
                'data: {"type":"response.output_item.added","item":{"id":"fc_1","type":"function_call","call_id":"call_1","name":"run_shell","arguments":"","status":"in_progress"},"output_index":0}',
                "",
                'event: response.function_call_arguments.delta',
                'data: {"type":"response.function_call_arguments.delta","item_id":"fc_1","output_index":0,"delta":"{\\"command\\":"}',
                "",
                'event: response.function_call_arguments.delta',
                'data: {"type":"response.function_call_arguments.delta","item_id":"fc_1","output_index":0,"delta":"\\"ls\\"}"}',
                "",
                'event: response.output_item.done',
                'data: {"type":"response.output_item.done","item":{"id":"fc_1","type":"function_call","call_id":"call_1","name":"run_shell","arguments":"{\\"command\\":\\"ls\\"}","status":"completed"},"output_index":0}',
                "",
                'event: response.completed',
                'data: {"type":"response.completed","response":{"id":"resp_tool_stream","model":"gpt-5.4","status":"completed","usage":{"input_tokens":11,"output_tokens":5}}}',
                "",
            ]
        )
    )

    body = b"".join(chunks)

    assert b"event: message_start" in body
    assert b'"type":"content_block_start"' in body
    assert b'"type":"tool_use"' in body
    assert b'"id":"call_1"' in body
    assert b'"type":"input_json_delta"' in body
    assert b'"partial_json":"{\\"command\\":"}' in body
    assert b'"partial_json":"\\"ls\\"}"}' in body
    assert b'"stop_reason":"tool_use"' in body
    assert b"event: message_stop" in body


def test_codex_bridge_stream_maps_incomplete_responses_to_max_tokens_stop_reason() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    chunks = list(
        executor._responses_sse_to_anthropic_events(  # type: ignore[attr-defined]
            [
                'event: response.created',
                'data: {"type":"response.created","response":{"id":"resp_incomplete","model":"gpt-5.4","status":"in_progress"}}',
                "",
                'event: response.output_text.delta',
                'data: {"type":"response.output_text.delta","output_index":0,"delta":"Hello"}',
                "",
                'event: response.incomplete',
                'data: {"type":"response.incomplete","response":{"id":"resp_incomplete","model":"gpt-5.4","status":"incomplete","incomplete_details":{"reason":"max_output_tokens"},"usage":{"input_tokens":9,"output_tokens":4}}}',
                "",
            ]
        )
    )

    body = b"".join(chunks)

    assert b"event: message_start" in body
    assert b'"type":"text_delta"' in body
    assert b'"stop_reason":"max_tokens"' in body
    assert b"event: message_stop" in body


def test_codex_bridge_stream_emits_anthropic_error_event_for_failed_response() -> None:
    executor = OpenAICodexOAuthBridgeExecutor(
        AppSettings(openai_codex_api_base_url="https://chatgpt.com/backend-api")
    )

    chunks = list(
        executor._responses_sse_to_anthropic_events(  # type: ignore[attr-defined]
            [
                'event: response.created',
                'data: {"type":"response.created","response":{"id":"resp_failed","model":"gpt-5.4","status":"in_progress"}}',
                "",
                'event: response.failed',
                'data: {"type":"response.failed","error":{"message":"upstream exploded"}}',
                "",
            ]
        )
    )

    body = b"".join(chunks)

    assert b"event: error" in body
    assert b"upstream exploded" in body


def test_claude_bridge_strips_reasoning_content_from_openai_chat_messages() -> None:
    executor = ClaudeMaxOAuthBridgeExecutor()
    request = UnifiedInferenceRequest(
        request_id="req_claude_chat",
        protocol="openai_chat",
        model="claude-max/claude-sonnet-4-6",
        model_profile="anthropic/claude-sonnet-4-6",
        upstream_model="claude-sonnet-4-6",
        auth_modes=["oauth_subscription"],
        provider="claude-max",
        payload={
            "model": "claude-max/claude-sonnet-4-6",
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {
                    "role": "assistant",
                    "content": "Thinking...",
                    "reasoning_content": [{"type": "text", "text": "private"}],
                },
                {"role": "user", "content": "Say hello"},
            ],
            "max_tokens": 16,
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=16,
    )

    payload = executor._to_anthropic_payload(request)  # type: ignore[attr-defined]

    assert payload["messages"] == [
        {"role": "assistant", "content": "Thinking..."},
        {"role": "user", "content": "Say hello"},
    ]
    assert payload["system"].startswith("x-anthropic-billing-header:")


def test_claude_bridge_defaults_max_tokens_for_openai_chat_requests() -> None:
    executor = ClaudeMaxOAuthBridgeExecutor()
    request = UnifiedInferenceRequest(
        request_id="req_claude_chat_default_max",
        protocol="openai_chat",
        model="claude-max/claude-sonnet-4-6",
        model_profile="anthropic/claude-sonnet-4-6",
        upstream_model="claude-sonnet-4-6",
        auth_modes=["oauth_subscription"],
        provider="claude-max",
        payload={
            "model": "claude-max/claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Say hello"}],
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=1,
    )

    payload = executor._to_anthropic_payload(request)  # type: ignore[attr-defined]

    assert payload["max_tokens"] == 4096


def test_claude_bridge_drops_top_p_when_temperature_is_present() -> None:
    executor = ClaudeMaxOAuthBridgeExecutor()
    request = UnifiedInferenceRequest(
        request_id="req_claude_sampling",
        protocol="anthropic_messages",
        model="claude-max/claude-sonnet-4-6",
        model_profile="anthropic/claude-sonnet-4-6",
        upstream_model="claude-sonnet-4-6",
        auth_modes=["oauth_subscription"],
        provider="claude-max",
        payload={
            "model": "claude-max/claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 16,
            "temperature": 0.7,
            "top_p": 1,
            "stream": True,
        },
        principal=Principal(
            user_id="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        ),
        estimated_units=16,
    )

    payload = executor._to_anthropic_payload(request)  # type: ignore[attr-defined]

    assert payload["temperature"] == 0.7
    assert "top_p" not in payload


def test_claude_bridge_stream_translates_text_delta_events_to_chat_chunks() -> None:
    executor = ClaudeMaxOAuthBridgeExecutor()

    chunks = list(
        executor._anthropic_sse_to_chat_chunks(  # type: ignore[attr-defined]
            [
                "event: message_start",
                'data: {"type":"message_start","message":{"model":"claude-sonnet-4-6","id":"msg_1","role":"assistant","usage":{"input_tokens":12,"output_tokens":2}}}',
                "",
                "event: content_block_start",
                'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
                "",
                "event: content_block_delta",
                'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}',
                "",
                "event: content_block_delta",
                'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"!"}}',
                "",
                "event: message_delta",
                'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"input_tokens":12,"output_tokens":5}}',
                "",
                "event: message_stop",
                'data: {"type":"message_stop"}',
                "",
            ]
        )
    )

    assert b'"delta":{"role":"assistant"}' in chunks[0]
    assert b'"delta":{"content":"Hello"}' in chunks[1]
    assert b'"delta":{"content":"!"}' in chunks[2]
    assert b'"finish_reason":"stop"' in chunks[3]
    assert chunks[4] == b"data: [DONE]\n\n"


def test_claude_refresh_posts_form_encoded_payload(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"access_token": "refreshed-token"}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, *, content: str, headers: dict[str, str]):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("enterprise_llm_proxy.services.openai_bridge.httpx.Client", lambda timeout=30.0: FakeClient())

    credential = ProviderCredential(
        id="cred-claude",
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct",
        scopes=["openid"],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token="expired-token",
        refresh_token="refresh-token",
        visibility=CredentialVisibility.PRIVATE,
    )

    refreshed = ClaudeMaxOAuthBridgeExecutor()._refresh_token(credential)  # type: ignore[attr-defined]

    assert refreshed == "refreshed-token"
    assert captured["url"] == "https://platform.claude.com/v1/oauth/token"
    assert captured["headers"] == {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
    }
    assert captured["content"] == (
        "grant_type=refresh_token&"
        "refresh_token=refresh-token&"
        "client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    )


def test_claude_refresh_rejects_expired_credentials_with_invalid_refresh_token(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    class FakeResponse:
        status_code = 400
        text = "invalid_grant"

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, *, content: str, headers: dict[str, str]):
            del url
            del content
            del headers
            return FakeResponse()

    monkeypatch.setattr("enterprise_llm_proxy.services.openai_bridge.httpx.Client", lambda timeout=30.0: FakeClient())

    credential = ProviderCredential(
        id="cred-claude-expired",
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct",
        scopes=["openid"],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token="expired-token",
        refresh_token="stale-refresh-token",
        visibility=CredentialVisibility.PRIVATE,
    )

    with pytest.raises(UpstreamCredentialInvalidError, match="Run 'routerctl claude bind' again"):
        ClaudeMaxOAuthBridgeExecutor()._refresh_token(credential)  # type: ignore[attr-defined]
