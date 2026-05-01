from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.domain.credentials import (
    CredentialState,
    CredentialVisibility,
    ProviderCredential,
)
from enterprise_llm_proxy.services.execution import (
    ExecutionResult,
    UpstreamCredentialInvalidError,
    UpstreamRateLimitError,
)
from enterprise_llm_proxy.services.identity import OidcIdentity
from enterprise_llm_proxy.services.model_catalog import ModelDefinition
from enterprise_llm_proxy.services.openai_bridge import (
    ClaudeMaxOAuthBridgeExecutor,
    OpenAICodexOAuthBridgeExecutor,
)


class FakeOidcClient:
    def exchange_code(self, code: str) -> dict[str, str]:
        return {"access_token": code}

    def fetch_userinfo(self, access_token: str) -> OidcIdentity:
        if access_token == "admin-code":
            return OidcIdentity(
                subject="u-admin",
                email="admin@example.com",
                name="Admin",
                team_ids=["platform"],
                role="admin",
            )

        return OidcIdentity(
            subject="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        )


class FakeLiteLLMExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def execute(self, request, credential) -> ExecutionResult:  # type: ignore[no-untyped-def]
        self.calls.append((request.protocol, request.model_profile, credential.id))
        return ExecutionResult(
            body={
                "id": "chatcmpl-123",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 18,
                    "total_tokens": 30,
                },
            },
            tokens_in=12,
            tokens_out=18,
        )


class FakeOAuthBridgeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._failed_once = False

    def execute(self, request, credential) -> ExecutionResult:  # type: ignore[no-untyped-def]
        self.calls.append((request.protocol, request.model_profile, credential.account_id))
        if credential.account_id == "acct-rate-limited" and not self._failed_once:
            self._failed_once = True
            raise UpstreamRateLimitError("subscription cooling down")

        return ExecutionResult(
            body={
                "id": "msg_123",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "hello"}],
                "usage": {"input_tokens": 10, "output_tokens": 14},
            },
            tokens_in=10,
            tokens_out=14,
        )


class FailingOAuthBridgeExecutor:
    def execute(self, request, credential) -> ExecutionResult:  # type: ignore[no-untyped-def]
        raise HTTPException(status_code=502, detail="upstream failed")


class InvalidCredentialOAuthBridgeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def execute(self, request, credential) -> ExecutionResult:  # type: ignore[no-untyped-def]
        self.calls.append((request.protocol, request.model_profile, credential.account_id))
        if credential.account_id == "acct-invalid-auth":
            raise UpstreamCredentialInvalidError("expired token")

        return ExecutionResult(
            body={
                "id": "msg_123",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "hello"}],
                "usage": {"input_tokens": 10, "output_tokens": 14},
            },
            tokens_in=10,
            tokens_out=14,
        )


class FakeOpenAICompatExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []
        self.stream_calls: list[tuple[str, str, str, str]] = []

    def execute(self, request, credential) -> ExecutionResult:  # type: ignore[no-untyped-def]
        self.calls.append(
            (
                request.protocol,
                request.model_profile,
                request.upstream_model,
                credential.account_id,
            )
        )
        if request.protocol == "openai_responses":
            return ExecutionResult(
                body={
                    "id": "resp_123",
                    "object": "response",
                    "output": [{"type": "message"}],
                    "usage": {"input_tokens": 8, "output_tokens": 12},
                },
                tokens_in=8,
                tokens_out=12,
            )
        return ExecutionResult(
            body={
                "id": "chatcmpl-compat",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hello from lm studio"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 12,
                    "total_tokens": 20,
                },
            },
            tokens_in=8,
            tokens_out=12,
        )

    def execute_stream(self, request, credential):  # type: ignore[no-untyped-def]
        self.stream_calls.append(
            (
                request.protocol,
                request.model_profile,
                request.upstream_model,
                credential.account_id,
            )
        )
        yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
        yield b"data: [DONE]\n\n"


class FakeLMStudioService:
    def __init__(self, model_ids: list[str]) -> None:
        self._model_ids = model_ids

    def build_system_credential(self) -> ProviderCredential:
        return ProviderCredential(
            id="cred-system-lmstudio",
            provider="openai_compat",
            auth_kind="api_key",
            account_id="lm-studio",
            scopes=["chat", "responses", "embeddings"],
            state=CredentialState.ACTIVE,
            expires_at=None,
            cooldown_until=None,
            access_token='{"api_key":"lm-token","base_url":"http://host.docker.internal:1234/v1"}',
            refresh_token=None,
            visibility=CredentialVisibility.ENTERPRISE_POOL,
            source="system_lm_studio",
            max_concurrency=1,
        )

    def list_models(self) -> list[ModelDefinition]:
        return [
            ModelDefinition(
                id=model_id,
                object="model",
                owned_by="openai_compat",
                provider="openai_compat",
                model_profile=model_id,
                upstream_model=model_id,
                display_name=model_id,
                supported_protocols=["openai_chat", "openai_responses", "openai_embeddings"],
                supported_clients=["codex"],
                auth_modes=["api_key"],
                description=f"{model_id} via LM Studio",
            )
            for model_id in self._model_ids
        ]

    def has_model(self, model_id: str) -> bool:
        return model_id in self._model_ids


def issue_token(client: TestClient, code: str) -> str:
    return client.post("/auth/oidc/callback", json={"code": code}).json()["access_token"]


def add_credential(
    client: TestClient,
    token: str,
    *,
    provider: str,
    auth_kind: str,
    account_id: str,
    refresh_token: str | None = None,
) -> dict[str, object]:
    response = client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": provider,
            "auth_kind": auth_kind,
            "account_id": account_id,
            "scopes": ["model:read"],
            "access_token": "access",
            "refresh_token": refresh_token,
            "max_concurrency": 2,
        },
    )
    return response.json()


def set_quota(client: TestClient, token: str, *, scope_type: str, scope_id: str, limit: int) -> None:
    response = client.post(
        "/admin/quotas",
        headers={"Authorization": f"Bearer {token}"},
        json={"scope_type": scope_type, "scope_id": scope_id, "limit": limit},
    )
    assert response.status_code == 200


def test_chat_completions_use_litellm_executor_and_record_usage() -> None:
    litellm = FakeLiteLLMExecutor()
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=litellm,
            oauth_bridge_executor=FakeOAuthBridgeExecutor(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    add_credential(
        client,
        admin_token,
        provider="openai",
        auth_kind="api_key",
        account_id="acct-openai-1",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai/gpt-4.1",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 64,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.json()["choices"][0]["message"]["content"] == "hello"
    assert litellm.calls == [("openai_chat", "openai/gpt-4.1", litellm.calls[0][2])]

    usage = client.get(
        "/admin/usage",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert usage.status_code == 200
    events = usage.json()["data"]
    assert events[0]["model_profile"] == "openai/gpt-4.1"
    assert events[0]["status"] == "success"


def test_models_endpoint_accepts_x_api_key_header() -> None:
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=FakeOAuthBridgeExecutor(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    add_credential(
        client,
        admin_token,
        provider="openai",
        auth_kind="api_key",
        account_id="acct-openai-1",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    key_response = client.post(
        "/developer/api-keys",
        headers={"Authorization": f"Bearer {member_token}"},
        json={"name": "Claude Code"},
    )
    api_key = key_response.json()["api_key"]

    response = client.get(
        "/v1/models",
        headers={"x-api-key": api_key},
    )

    assert response.status_code == 200


def test_anthropic_messages_use_oauth_bridge_and_fallback_from_rate_limit() -> None:
    oauth_bridge = FakeOAuthBridgeExecutor()
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=oauth_bridge,
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    first = add_credential(
        client,
        admin_token,
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct-rate-limited",
        refresh_token="refresh-1",
    )
    second = add_credential(
        client,
        admin_token,
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct-healthy",
        refresh_token="refresh-2",
    )
    set_quota(client, admin_token, scope_type="team", scope_id="platform", limit=1000)

    response = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "claude-max/claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 128,
        },
    )

    assert response.status_code == 200
    assert response.json()["content"][0]["text"] == "hello"
    assert oauth_bridge.calls == [
        ("anthropic_messages", "anthropic/claude-sonnet-4-20250514", "acct-rate-limited"),
        ("anthropic_messages", "anthropic/claude-sonnet-4-20250514", "acct-healthy"),
    ]

    credentials = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    by_id = {item["id"]: item for item in credentials.json()["data"]}
    assert by_id[str(first["id"])]["state"] == "cooldown"
    assert by_id[str(second["id"])]["state"] == "active"


def test_anthropic_messages_passthrough_cooldown_when_all_oauth_credentials_rate_limited() -> None:
    oauth_bridge = FakeOAuthBridgeExecutor()
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=oauth_bridge,
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    only = add_credential(
        client,
        admin_token,
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct-rate-limited",
        refresh_token="refresh-1",
    )
    set_quota(client, admin_token, scope_type="team", scope_id="platform", limit=1000)

    response = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "claude-max/claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 128,
        },
    )

    assert response.status_code == 429
    assert "cooldown" in response.json()["detail"]

    credentials = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    by_id = {item["id"]: item for item in credentials.json()["data"]}
    assert by_id[str(only["id"])]["state"] == "cooldown"


def test_anthropic_messages_disable_invalid_oauth_credential_and_retry_healthy_one() -> None:
    oauth_bridge = InvalidCredentialOAuthBridgeExecutor()
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=oauth_bridge,
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    invalid = add_credential(
        client,
        admin_token,
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct-invalid-auth",
        refresh_token="refresh-invalid",
    )
    healthy = add_credential(
        client,
        admin_token,
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct-healthy",
        refresh_token="refresh-healthy",
    )
    set_quota(client, admin_token, scope_type="team", scope_id="platform", limit=1000)

    first = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "claude-max/claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 128,
        },
    )
    second = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "claude-max/claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "Say hello again"}],
            "max_tokens": 128,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert oauth_bridge.calls == [
        ("anthropic_messages", "anthropic/claude-sonnet-4-20250514", "acct-invalid-auth"),
        ("anthropic_messages", "anthropic/claude-sonnet-4-20250514", "acct-healthy"),
        ("anthropic_messages", "anthropic/claude-sonnet-4-20250514", "acct-healthy"),
    ]

    credentials = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    by_id = {item["id"]: item for item in credentials.json()["data"]}
    assert by_id[str(invalid["id"])]["state"] == "disabled"
    assert by_id[str(invalid["id"])]["concurrent_leases"] == 0
    assert by_id[str(healthy["id"])]["state"] == "active"


def test_anthropic_messages_skip_credentials_that_do_not_list_requested_model() -> None:
    oauth_bridge = InvalidCredentialOAuthBridgeExecutor()
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=oauth_bridge,
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    incompatible = client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "provider": "claude-max",
            "auth_kind": "oauth_subscription",
            "account_id": "acct-invalid-auth",
            "scopes": ["model:read"],
            "access_token": "access",
            "refresh_token": "refresh-invalid",
            "max_concurrency": 2,
            "catalog_info": {"available_models": ["claude-opus-4-20250514"]},
        },
    ).json()
    compatible = client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "provider": "claude-max",
            "auth_kind": "oauth_subscription",
            "account_id": "acct-healthy",
            "scopes": ["model:read"],
            "access_token": "access",
            "refresh_token": "refresh-healthy",
            "max_concurrency": 2,
            "catalog_info": {"available_models": ["claude-sonnet-4-20250514"]},
        },
    ).json()
    set_quota(client, admin_token, scope_type="team", scope_id="platform", limit=1000)

    response = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "claude-max/claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 128,
        },
    )

    assert response.status_code == 200
    assert oauth_bridge.calls == [
        ("anthropic_messages", "anthropic/claude-sonnet-4-20250514", "acct-healthy"),
    ]

    credentials = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    by_id = {item["id"]: item for item in credentials.json()["data"]}
    assert by_id[str(incompatible["id"])]["state"] == "active"
    assert by_id[str(compatible["id"])]["state"] == "active"


def test_gpt5_codex_can_serve_claude_code_via_openai_oauth_bridge() -> None:
    oauth_bridge = FakeOAuthBridgeExecutor()
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=oauth_bridge,
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "provider": "openai-codex",
            "auth_kind": "codex_chatgpt_oauth_managed",
            "account_id": "acct-codex-oauth",
            "scopes": ["openid", "offline_access"],
            "access_token": "oauth-access",
            "refresh_token": "oauth-refresh",
            "max_concurrency": 2,
            "visibility": "private",
            "owner_principal_id": "u-member",
            "source": "codex_chatgpt_oauth_managed",
        },
    )

    response = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai-codex/gpt-5-codex",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 128,
        },
    )

    assert response.status_code == 200
    assert response.json()["content"][0]["text"] == "hello"
    assert oauth_bridge.calls == [
        ("anthropic_messages", "openai-codex/gpt-5-codex", "acct-codex-oauth"),
    ]


def test_non_streaming_success_releases_selected_codex_credential() -> None:
    oauth_bridge = FakeOAuthBridgeExecutor()
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=oauth_bridge,
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    created = add_credential(
        client,
        admin_token,
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-codex-oauth",
        refresh_token="refresh-1",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 8,
        },
    )

    assert response.status_code == 200
    credentials = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    by_id = {item["id"]: item for item in credentials.json()["data"]}
    assert by_id[str(created["id"])]["concurrent_leases"] == 0


def test_codex_chat_completions_filters_unsupported_temperature(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    observed_payloads: list[dict[str, object]] = []

    def fake_execute(self, request, credential):  # type: ignore[no-untyped-def]
        assert request.provider == "openai-codex"
        assert credential.provider == "openai-codex"
        payload, _endpoint = self._build_request(request)  # type: ignore[attr-defined]
        observed_payloads.append(payload)
        return ExecutionResult(
            body={
                "id": "chatcmpl-codex",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 4,
                    "total_tokens": 12,
                },
            },
            tokens_in=8,
            tokens_out=4,
        )

    monkeypatch.setattr(
        OpenAICodexOAuthBridgeExecutor,
        "execute",
        fake_execute,
        raising=False,
    )
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    add_credential(
        client,
        admin_token,
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-codex-oauth",
        refresh_token="refresh-1",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 8,
            "temperature": 0.8,
        },
    )

    assert response.status_code == 200
    assert observed_payloads
    assert "temperature" not in observed_payloads[0]


def test_non_streaming_upstream_error_releases_selected_codex_credential() -> None:
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=FailingOAuthBridgeExecutor(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    created = add_credential(
        client,
        admin_token,
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-codex-oauth",
        refresh_token="refresh-1",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 8,
        },
    )

    assert response.status_code == 502
    credentials = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    by_id = {item["id"]: item for item in credentials.json()["data"]}
    assert by_id[str(created["id"])]["concurrent_leases"] == 0


def test_app_reuses_persisted_quota_and_usage_across_app_recreation(
    postgres_database_url: str,
) -> None:
    settings = AppSettings(database_url=postgres_database_url)
    litellm = FakeLiteLLMExecutor()
    client = TestClient(
        create_app(
            settings=settings,
            oidc_client=FakeOidcClient(),
            litellm_executor=litellm,
            oauth_bridge_executor=FakeOAuthBridgeExecutor(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    add_credential(
        client,
        admin_token,
        provider="openai",
        auth_kind="api_key",
        account_id="acct-openai-1",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=40)

    first = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai/gpt-4.1",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 20,
        },
    )

    assert first.status_code == 200

    recreated_client = TestClient(
        create_app(
            settings=settings,
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=FakeOAuthBridgeExecutor(),
        )
    )

    usage = recreated_client.get(
        "/admin/usage",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    quotas = recreated_client.get(
        "/admin/quotas",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    second = recreated_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai/gpt-4.1",
            "messages": [{"role": "user", "content": "Say hello again"}],
            "max_tokens": 20,
        },
    )

    assert usage.status_code == 200
    assert len(usage.json()["data"]) == 1
    assert quotas.status_code == 200
    assert quotas.json()["data"] == [{"scope_type": "user", "scope_id": "u-member", "limit": 40}]
    assert second.status_code == 403


def test_app_startup_resets_stale_persisted_credential_leases(
    postgres_database_url: str,
) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from enterprise_llm_proxy.repositories.models import ProviderCredentialRecord

    settings = AppSettings(
        database_url=postgres_database_url,
        credential_lease_ttl_seconds=60,
    )
    client = TestClient(
        create_app(
            settings=settings,
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=FakeOAuthBridgeExecutor(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    created = add_credential(
        client,
        admin_token,
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-stale-lease",
    )
    engine = create_engine(postgres_database_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        record = session.get(ProviderCredentialRecord, str(created["id"]))
        assert record is not None
        record.concurrent_leases = 1
        record.updated_at = datetime.now(UTC) - timedelta(minutes=10)
        session.commit()

    with TestClient(
        create_app(
            settings=settings,
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=FakeOAuthBridgeExecutor(),
        )
    ):
        pass

    with session_factory() as session:
        record = session.get(ProviderCredentialRecord, str(created["id"]))
        assert record is not None
        assert record.concurrent_leases == 0
    engine.dispose()


def test_private_codex_oauth_credentials_are_not_shared_without_promotion() -> None:
    oauth_bridge = FakeOAuthBridgeExecutor()
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=oauth_bridge,
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "provider": "openai-codex",
            "auth_kind": "codex_chatgpt_oauth_managed",
            "account_id": "acct-codex-oauth",
            "scopes": ["openid", "offline_access"],
            "access_token": "oauth-access",
            "refresh_token": "oauth-refresh",
            "max_concurrency": 2,
            "visibility": "private",
            "owner_principal_id": "u-member",
            "source": "codex_chatgpt_oauth_managed",
        },
    )

    member_response = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai-codex/gpt-5-codex",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 64,
        },
    )
    admin_response = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "model": "openai-codex/gpt-5-codex",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 64,
        },
    )

    assert member_response.status_code == 200
    assert admin_response.status_code == 503
    assert admin_response.json()["detail"] == (
        "No openai-codex upstream credentials are bound or visible for this principal"
    )


def test_over_quota_request_is_rejected_before_execution() -> None:
    litellm = FakeLiteLLMExecutor()
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=litellm,
            oauth_bridge_executor=FakeOAuthBridgeExecutor(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    add_credential(
        client,
        admin_token,
        provider="openai",
        auth_kind="api_key",
        account_id="acct-openai-1",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=5)

    response = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai/gpt-4.1",
            "input": "Please generate a fairly long answer",
            "max_output_tokens": 200,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Quota exceeded"
    assert litellm.calls == []


def test_lm_studio_system_credential_serves_chat_completions() -> None:
    compat = FakeOpenAICompatExecutor()
    client = TestClient(
        create_app(
            settings=AppSettings(
                lm_studio_enabled=True,
                lm_studio_api_key="lm-token",
            ),
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=FakeOAuthBridgeExecutor(),
            openai_compat_executor=compat,
            lmstudio_service=FakeLMStudioService(["zai-org/glm-4.7-flash"]),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "zai-org/glm-4.7-flash",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 64,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hello from lm studio"
    assert compat.calls == [
        ("openai_chat", "zai-org/glm-4.7-flash", "zai-org/glm-4.7-flash", "lm-studio")
    ]


def test_lm_studio_system_credential_serves_responses() -> None:
    compat = FakeOpenAICompatExecutor()
    client = TestClient(
        create_app(
            settings=AppSettings(
                lm_studio_enabled=True,
                lm_studio_api_key="lm-token",
            ),
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=FakeOAuthBridgeExecutor(),
            openai_compat_executor=compat,
            lmstudio_service=FakeLMStudioService(["openai/gpt-oss-120b"]),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    response = client.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai/gpt-oss-120b",
            "input": "Say hello",
            "max_output_tokens": 64,
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == "resp_123"
    assert compat.calls == [
        ("openai_responses", "openai/gpt-oss-120b", "openai/gpt-oss-120b", "lm-studio")
    ]


def test_lm_studio_system_credential_serves_streaming_chat_completions() -> None:
    compat = FakeOpenAICompatExecutor()
    client = TestClient(
        create_app(
            settings=AppSettings(
                lm_studio_enabled=True,
                lm_studio_api_key="lm-token",
            ),
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=FakeOAuthBridgeExecutor(),
            openai_compat_executor=compat,
            lmstudio_service=FakeLMStudioService(["minimax/minimax-m2.5"]),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "minimax/minimax-m2.5",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": True,
        },
    ) as response:
        body = b"".join(response.iter_bytes())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b'data: {"choices":[{"delta":{"content":"hello"}}]}' in body
    assert b"data: [DONE]" in body
    assert compat.stream_calls == [
        ("openai_chat", "minimax/minimax-m2.5", "minimax/minimax-m2.5", "lm-studio")
    ]


def test_codex_oauth_serves_streaming_chat_completions(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def fake_execute_stream(self, request, credential):  # type: ignore[no-untyped-def]
        assert request.provider == "openai-codex"
        assert credential.provider == "openai-codex"
        yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(
        OpenAICodexOAuthBridgeExecutor,
        "execute_stream",
        fake_execute_stream,
        raising=False,
    )

    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    created = add_credential(
        client,
        admin_token,
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-codex-stream",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": True,
        },
    ) as response:
        body = b"".join(response.iter_bytes())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b'data: {"choices":[{"delta":{"content":"hello"}}]}' in body
    assert b"data: [DONE]" in body
    credentials = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    by_id = {item["id"]: item for item in credentials.json()["data"]}
    assert by_id[str(created["id"])]["concurrent_leases"] == 0


def test_codex_streaming_generator_close_releases_credential(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def fake_execute_stream(self, request, credential):  # type: ignore[no-untyped-def]
        assert request.provider == "openai-codex"
        assert credential.provider == "openai-codex"
        yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
        yield b'data: {"choices":[{"delta":{"content":"later"}}]}\n\n'

    monkeypatch.setattr(
        OpenAICodexOAuthBridgeExecutor,
        "execute_stream",
        fake_execute_stream,
        raising=False,
    )

    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    created = add_credential(
        client,
        admin_token,
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-codex-stream-close",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": True,
        },
    ) as response:
        next(response.iter_bytes())

    credentials = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    by_id = {item["id"]: item for item in credentials.json()["data"]}
    assert by_id[str(created["id"])]["concurrent_leases"] == 0


def test_codex_streaming_rate_limit_marks_cooldown_without_leaking_credential(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def fake_execute_stream(self, request, credential):  # type: ignore[no-untyped-def]
        assert request.provider == "openai-codex"
        assert credential.provider == "openai-codex"
        raise UpstreamRateLimitError("subscription cooling down")
        yield b""

    monkeypatch.setattr(
        OpenAICodexOAuthBridgeExecutor,
        "execute_stream",
        fake_execute_stream,
        raising=False,
    )

    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
        ),
        raise_server_exceptions=False,
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    created = add_credential(
        client,
        admin_token,
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-codex-stream-rate-limited",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": True,
        },
    ) as response:
        list(response.iter_bytes())

    credentials = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    by_id = {item["id"]: item for item in credentials.json()["data"]}
    assert by_id[str(created["id"])]["state"] == "cooldown"
    assert by_id[str(created["id"])]["concurrent_leases"] == 0


def test_codex_streaming_preflight_failure_returns_http_502(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def fake_execute_stream(self, request, credential):  # type: ignore[no-untyped-def]
        assert request.provider == "openai-codex"
        assert credential.provider == "openai-codex"
        raise HTTPException(status_code=502, detail="Upstream request failed: tls timeout")
        yield b""

    monkeypatch.setattr(
        OpenAICodexOAuthBridgeExecutor,
        "execute_stream",
        fake_execute_stream,
        raising=False,
    )

    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
        ),
        raise_server_exceptions=False,
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    add_credential(
        client,
        admin_token,
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-codex-stream-preflight-failure",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": True,
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Upstream request failed: tls timeout"


def test_codex_oauth_serves_streaming_anthropic_messages(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def fail_if_non_streaming(self, request, credential):  # type: ignore[no-untyped-def]
        raise AssertionError("non-streaming fallback should not be used")

    def fake_execute_stream(self, request, credential):  # type: ignore[no-untyped-def]
        assert request.provider == "openai-codex"
        assert request.protocol == "anthropic_messages"
        assert credential.provider == "openai-codex"
        yield (
            b'event: message_start\n'
            b'data: {"type":"message_start","message":{"id":"msg_1","type":"message","role":"assistant","model":"gpt-5.4","usage":{"input_tokens":0,"output_tokens":0}}}\n\n'
        )
        yield (
            b'event: message_stop\n'
            b'data: {"type":"message_stop"}\n\n'
        )

    monkeypatch.setattr(
        OpenAICodexOAuthBridgeExecutor,
        "execute",
        fail_if_non_streaming,
        raising=False,
    )
    monkeypatch.setattr(
        OpenAICodexOAuthBridgeExecutor,
        "execute_stream",
        fake_execute_stream,
        raising=False,
    )

    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
        ),
        raise_server_exceptions=False,
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    add_credential(
        client,
        admin_token,
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-codex-anthropic-stream",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    with client.stream(
        "POST",
        "/v1/messages",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": True,
            "max_tokens": 16,
        },
    ) as response:
        body = b"".join(response.iter_bytes())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b"event: message_start" in body
    assert b"event: message_stop" in body


def test_codex_oauth_serves_streaming_anthropic_messages_with_mcp_payload(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def fail_if_non_streaming(self, request, credential):  # type: ignore[no-untyped-def]
        raise AssertionError("non-streaming fallback should not be used for MCP payloads")

    def fake_execute_stream(self, request, credential):  # type: ignore[no-untyped-def]
        assert request.provider == "openai-codex"
        assert request.protocol == "anthropic_messages"
        assert request.payload["mcp_servers"] == [
            {
                "type": "url",
                "name": "github",
                "url": "https://mcp.example.test/sse",
            }
        ]
        assert request.payload["tools"] == [
            {
                "type": "mcp_toolset",
                "mcp_server_name": "github",
                "default_config": {"enabled": False},
                "configs": {"get_issue": {"enabled": True}},
                "require_approval": "never",
            }
        ]
        assert credential.provider == "openai-codex"
        yield (
            b'event: message_start\n'
            b'data: {"type":"message_start","message":{"id":"msg_1","type":"message","role":"assistant","model":"gpt-5.4","usage":{"input_tokens":0,"output_tokens":0}}}\n\n'
        )
        yield (
            b'event: message_stop\n'
            b'data: {"type":"message_stop"}\n\n'
        )

    monkeypatch.setattr(
        OpenAICodexOAuthBridgeExecutor,
        "execute",
        fail_if_non_streaming,
        raising=False,
    )
    monkeypatch.setattr(
        OpenAICodexOAuthBridgeExecutor,
        "execute_stream",
        fake_execute_stream,
        raising=False,
    )

    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
        ),
        raise_server_exceptions=False,
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    add_credential(
        client,
        admin_token,
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-codex-anthropic-mcp-stream",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    with client.stream(
        "POST",
        "/v1/messages",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "openai-codex/gpt-5.4",
            "messages": [{"role": "user", "content": "Use GitHub MCP"}],
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
                    "default_config": {"enabled": False},
                    "configs": {"get_issue": {"enabled": True}},
                    "require_approval": "never",
                }
            ],
            "stream": True,
            "max_tokens": 16,
        },
    ) as response:
        body = b"".join(response.iter_bytes())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b"event: message_start" in body
    assert b"event: message_stop" in body


def test_claude_oauth_serves_streaming_openai_chat_completions(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def fake_execute_chat_stream(self, request, credential):  # type: ignore[no-untyped-def]
        assert request.provider == "claude-max"
        assert request.protocol == "openai_chat"
        assert credential.provider == "claude-max"
        yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    monkeypatch.setattr(
        ClaudeMaxOAuthBridgeExecutor,
        "execute_chat_stream",
        fake_execute_chat_stream,
        raising=False,
    )

    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    add_credential(
        client,
        admin_token,
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct-claude-stream",
        refresh_token="refresh-1",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "claude-max/claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": True,
            "max_tokens": 16,
        },
    ) as response:
        body = b"".join(response.iter_bytes())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b'data: {"choices":[{"delta":{"content":"hello"}}]}' in body
    assert b"data: [DONE]" in body


def test_known_byok_provider_model_does_not_fallback_to_openai_compat() -> None:
    compat = FakeOpenAICompatExecutor()
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeLiteLLMExecutor(),
            oauth_bridge_executor=FakeOAuthBridgeExecutor(),
            openai_compat_executor=compat,
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    add_credential(
        client,
        member_token,
        provider="openai_compat",
        auth_kind="api_key",
        account_id="custom-openai-compatible",
    )
    set_quota(client, admin_token, scope_type="user", scope_id="u-member", limit=1000)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "model": "minimax/minimax-m2.5",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 64,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "No minimax upstream credentials are bound or visible for this principal"
    )
    assert compat.calls == []
