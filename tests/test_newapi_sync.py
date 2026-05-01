from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import HTTPException
from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.domain.credentials import (
    CredentialState,
    CredentialVisibility,
    ProviderCredential,
)
from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.services.execution import ExecutionResult, UpstreamCredentialInvalidError
from enterprise_llm_proxy.services.identity import OidcIdentity
from enterprise_llm_proxy.services.newapi import NewApiCredentialSyncService


class FakeOidcClient:
    def exchange_code(self, code: str) -> dict[str, str]:
        return {"access_token": code}

    def fetch_userinfo(self, access_token: str) -> OidcIdentity:
        return OidcIdentity(
            subject="u-admin" if access_token == "admin-code" else "u-member",
            email="admin@example.com" if access_token == "admin-code" else "member@example.com",
            name="Admin" if access_token == "admin-code" else "Member",
            team_ids=["platform"],
            role="admin" if access_token == "admin-code" else "member",
        )


class FakeNewApiClient:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.updated: list[dict[str, object]] = []
        self._channels: dict[str, dict[str, object]] = {}
        self._next_id = 100

    def add_channel(self, payload: dict[str, object]) -> dict[str, object]:
        channel = dict(payload["channel"])  # type: ignore[index]
        channel["id"] = self._next_id
        self._next_id += 1
        self._channels[str(channel["name"])] = channel
        self.created.append(payload)
        return {"success": True}

    def update_channel(self, payload: dict[str, object]) -> dict[str, object]:
        self.updated.append(dict(payload))
        self._channels[str(payload["name"])] = dict(payload)
        return {"success": True}

    def find_channel_by_name(self, name: str) -> dict[str, object] | None:
        channel = self._channels.get(name)
        return dict(channel) if channel is not None else None


class FakeOAuthBridgeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def execute(self, request, credential) -> ExecutionResult:  # type: ignore[no-untyped-def]
        self.calls.append((request.protocol, request.upstream_model, credential.id))
        return ExecutionResult(
            body={
                "id": "msg_test",
                "type": "message",
                "model": request.upstream_model,
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            tokens_in=1,
            tokens_out=1,
        )


class FakeCodexOAuthBridgeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.stream_calls: list[tuple[str, str, str]] = []

    def execute(self, request, credential) -> ExecutionResult:  # type: ignore[no-untyped-def]
        self.calls.append((request.protocol, request.upstream_model, credential.id))
        if request.protocol == "openai_responses":
            return ExecutionResult(
                body={
                    "id": "resp_test",
                    "object": "response",
                    "model": request.upstream_model,
                    "output": [],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
                tokens_in=1,
                tokens_out=1,
            )
        return ExecutionResult(
            body={
                "id": "chatcmpl_test",
                "object": "chat.completion",
                "model": request.upstream_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
            tokens_in=1,
            tokens_out=1,
        )

    def stream_openai_codex(self, request, credential):  # type: ignore[no-untyped-def]
        self.stream_calls.append((request.protocol, request.upstream_model, credential.id))
        yield b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        yield b"data: [DONE]\n\n"


class InvalidOAuthBridgeExecutor:
    def execute(self, request, credential) -> ExecutionResult:  # type: ignore[no-untyped-def]
        raise UpstreamCredentialInvalidError("invalid oauth credential")


class FailingStreamingOAuthBridgeExecutor(FakeOAuthBridgeExecutor):
    async def stream_claude_max(self, request, credential, extra_headers):  # type: ignore[no-untyped-def]
        del request
        del credential
        del extra_headers
        raise HTTPException(status_code=502, detail="upstream rejected sampling params")
        yield b""


def settings(**overrides: object) -> AppSettings:
    values = {
        "newapi_sync_enabled": True,
        "newapi_enterprise_group": "enterprise",
        "bridge_base_url_for_newapi": "https://router.example.com",
        "bridge_upstream_api_key": "bridge-secret",
    }
    values.update(overrides)
    return AppSettings(**values)


def issue_token(client: TestClient) -> str:
    return client.post("/auth/oidc/callback", json={"code": "member-code"}).json()["access_token"]


def issue_admin_token(client: TestClient) -> str:
    return client.post("/auth/oidc/callback", json={"code": "admin-code"}).json()["access_token"]


def principal() -> Principal:
    return Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )


def test_codex_import_share_and_unshare_sync_newapi_channel_groups() -> None:
    newapi = FakeNewApiClient()
    client = TestClient(
        create_app(
            settings=settings(),
            oidc_client=FakeOidcClient(),
            newapi_client=newapi,
        )
    )
    token = issue_token(client)

    imported = client.post(
        "/me/upstream-credentials/codex/import",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": "openai-account-1",
            "access_token": "oauth-access",
            "refresh_token": "oauth-refresh",
            "scopes": ["openid", "offline_access"],
            "expires_at": "2030-01-01T00:00:00+00:00",
            "available_models": ["gpt-5.4"],
        },
    )
    credential_id = imported.json()["id"]

    created_channel = newapi.created[0]["channel"]  # type: ignore[index]
    assert created_channel["type"] == 1  # OpenAI-compatible bridge to router
    assert created_channel["key"] == "bridge-secret"
    assert created_channel["base_url"] == (
        f"https://router.example.com/bridge/upstreams/credentials/{credential_id}/openai"
    )
    assert created_channel["group"] == "private-u-member"
    assert created_channel["models"] == "gpt-5.4"
    assert created_channel["tag"] == "router-oauth-bridge"

    shared = client.post(
        f"/me/upstream-credentials/{credential_id}/share",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert shared.status_code == 200
    assert newapi.updated[-1]["group"] == "private-u-member,enterprise"

    unshared = client.post(
        f"/me/upstream-credentials/{credential_id}/unshare",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert unshared.status_code == 200
    assert newapi.updated[-1]["group"] == "private-u-member"


def test_claude_import_syncs_anthropic_channel_to_bridge() -> None:
    newapi = FakeNewApiClient()
    client = TestClient(
        create_app(
            settings=settings(),
            oidc_client=FakeOidcClient(),
            newapi_client=newapi,
        )
    )
    token = issue_token(client)

    imported = client.post(
        "/me/upstream-credentials/claude-max/import",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": "claude-account-1",
            "access_token": "claude-access",
            "refresh_token": "claude-refresh",
            "scopes": ["user:inference"],
            "expires_at": datetime(2030, 1, 1, tzinfo=UTC).isoformat(),
            "available_models": ["claude-sonnet-4-6"],
        },
    )

    credential_id = imported.json()["id"]
    channel = newapi.created[0]["channel"]  # type: ignore[index]
    assert channel["type"] == 14  # Anthropic
    assert channel["key"] == "bridge-secret"
    assert channel["base_url"] == (
        f"https://router.example.com/bridge/upstreams/credentials/{credential_id}/anthropic"
    )
    assert channel["models"] == "claude-sonnet-4-6"
    assert channel["group"] == "private-u-member"


def test_openai_compat_lmstudio_syncs_as_openai_channel_with_model_mapping() -> None:
    newapi = FakeNewApiClient()
    service = NewApiCredentialSyncService(
        settings=settings(),
        client=newapi,
    )
    credential = ProviderCredential(
        id="cred-system-lmstudio",
        provider="openai_compat",
        auth_kind="api_key",
        account_id="lm-studio",
        provider_alias="lmstudio",
        scopes=[],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token=json.dumps(
            {
                "api_key": "lmstudio-key",
                "base_url": "http://host.docker.internal:1234/v1",
            }
        ),
        refresh_token=None,
        visibility=CredentialVisibility.ENTERPRISE_POOL,
        source="system_lm_studio",
        catalog_info={"available_models": ["gemma-4-31b-it", "zai-org/glm-4.7-flash"]},
    )

    result = service.sync_credential(credential, principal(), shared=True)

    assert result.enabled is True
    channel = newapi.created[0]["channel"]  # type: ignore[index]
    assert channel["type"] == 1
    assert channel["key"] == "lmstudio-key"
    assert channel["base_url"] == "http://host.docker.internal:1234"
    assert channel["models"] == "lmstudio/gemma-4-31b-it,lmstudio/zai-org/glm-4.7-flash"
    assert json.loads(channel["model_mapping"]) == {
        "lmstudio/gemma-4-31b-it": "gemma-4-31b-it",
        "lmstudio/zai-org/glm-4.7-flash": "zai-org/glm-4.7-flash",
    }
    assert channel["group"] == "private-u-member,enterprise"
    assert channel["tag"] == "router-compat"


def test_native_byok_provider_syncs_as_newapi_provider_channel() -> None:
    newapi = FakeNewApiClient()
    service = NewApiCredentialSyncService(
        settings=settings(),
        client=newapi,
    )
    credential = ProviderCredential(
        id="cred-zhipu",
        provider="zhipu",
        auth_kind="api_key",
        account_id="zhipu-account",
        scopes=[],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token="zhipu-key",
        refresh_token=None,
        visibility=CredentialVisibility.ENTERPRISE_POOL,
        source="byok_api_key",
        catalog_info={"available_models": ["glm-4.5-flash"]},
    )

    result = service.sync_credential(credential, principal(), shared=True)

    assert result.enabled is True
    channel = newapi.created[0]["channel"]  # type: ignore[index]
    assert channel["type"] == 26
    assert channel["key"] == "zhipu-key"
    assert channel["base_url"] == "https://open.bigmodel.cn"
    assert channel["models"] == "zhipu/glm-4.5-flash"
    assert json.loads(channel["model_mapping"]) == {
        "zhipu/glm-4.5-flash": "glm-4.5-flash",
    }
    assert channel["tag"] == "router-byok"


def test_jina_byok_provider_syncs_rerank_and_embedding_models() -> None:
    newapi = FakeNewApiClient()
    service = NewApiCredentialSyncService(
        settings=settings(),
        client=newapi,
    )
    credential = ProviderCredential(
        id="cred-jina",
        provider="jina",
        auth_kind="api_key",
        account_id="jina-account",
        scopes=[],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token="jina-key",
        refresh_token=None,
        visibility=CredentialVisibility.ENTERPRISE_POOL,
        source="byok_api_key",
        catalog_info={"available_models": ["jina-embeddings-v4", "jina-reranker-v3"]},
    )

    result = service.sync_credential(credential, principal(), shared=True)

    assert result.enabled is True
    channel = newapi.created[0]["channel"]  # type: ignore[index]
    assert channel["type"] == 38
    assert channel["key"] == "jina-key"
    assert channel["base_url"] == "https://api.jina.ai"
    assert channel["models"] == "jina/jina-embeddings-v4,jina/jina-reranker-v3"
    assert json.loads(channel["model_mapping"]) == {
        "jina/jina-embeddings-v4": "jina-embeddings-v4",
        "jina/jina-reranker-v3": "jina-reranker-v3",
    }
    assert channel["tag"] == "router-byok"


def test_jina_byok_provider_uses_default_models_when_catalog_is_empty() -> None:
    newapi = FakeNewApiClient()
    service = NewApiCredentialSyncService(
        settings=settings(),
        client=newapi,
    )
    credential = ProviderCredential(
        id="cred-jina",
        provider="jina",
        auth_kind="api_key",
        account_id="jina-account",
        scopes=[],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token="jina-key",
        refresh_token=None,
        visibility=CredentialVisibility.ENTERPRISE_POOL,
        source="byok_api_key",
    )

    result = service.sync_credential(credential, principal(), shared=True)

    assert result.enabled is True
    channel = newapi.created[0]["channel"]  # type: ignore[index]
    assert "jina/jina-embeddings-v4" in str(channel["models"])
    assert "jina/jina-reranker-v3" in str(channel["models"])


def test_newapi_sync_skips_inactive_credentials() -> None:
    newapi = FakeNewApiClient()
    service = NewApiCredentialSyncService(
        settings=settings(),
        client=newapi,
    )
    credential = ProviderCredential(
        id="cred-disabled-claude",
        provider="claude-max",
        auth_kind="oauth",
        account_id="claude-account",
        scopes=[],
        state=CredentialState.DISABLED,
        expires_at=None,
        cooldown_until=None,
        access_token="disabled-token",
        refresh_token=None,
        visibility=CredentialVisibility.ENTERPRISE_POOL,
    )

    result = service.sync_credential(credential, principal(), shared=True)

    assert result.enabled is False
    assert result.action == "skipped_inactive"
    assert newapi.created == []
    assert newapi.updated == []


def test_claude_reimport_reactivates_disabled_credential() -> None:
    client = TestClient(
        create_app(
            settings=settings(newapi_sync_enabled=False),
            oidc_client=FakeOidcClient(),
            oauth_bridge_executor=InvalidOAuthBridgeExecutor(),
        )
    )
    token = issue_token(client)

    imported = client.post(
        "/me/upstream-credentials/claude-max/import",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": "claude-account-1",
            "access_token": "stale-claude-access",
            "refresh_token": "claude-refresh",
            "scopes": ["user:inference"],
            "expires_at": datetime(2030, 1, 1, tzinfo=UTC).isoformat(),
            "available_models": ["claude-sonnet-4-6"],
        },
    )
    credential_id = imported.json()["id"]

    response = client.post(
        f"/bridge/upstreams/credentials/{credential_id}/anthropic/v1/messages",
        headers={"x-api-key": "bridge-secret"},
        json={"model": "claude-sonnet-4-6", "max_tokens": 8, "messages": []},
    )
    assert response.status_code == 401
    listed = client.get(
        "/me/upstream-credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.json()["data"][0]["state"] == "disabled"

    reimported = client.post(
        "/me/upstream-credentials/claude-max/import",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": "claude-account-1",
            "access_token": "fresh-claude-access",
            "refresh_token": "fresh-claude-refresh",
            "scopes": ["user:inference"],
            "expires_at": datetime(2031, 1, 1, tzinfo=UTC).isoformat(),
            "available_models": ["claude-sonnet-4-6"],
        },
    )

    assert reimported.status_code == 201
    assert reimported.json()["id"] == credential_id
    assert reimported.json()["state"] == "active"


def test_admin_can_backfill_existing_credentials_to_newapi() -> None:
    newapi = FakeNewApiClient()
    client = TestClient(
        create_app(
            settings=settings(),
            oidc_client=FakeOidcClient(),
            newapi_client=newapi,
        )
    )
    member_token = issue_token(client)
    admin_token = issue_admin_token(client)
    client.post(
        "/me/upstream-credentials/codex/import",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "account_id": "openai-account-1",
            "access_token": "oauth-access",
            "refresh_token": "oauth-refresh",
            "available_models": ["gpt-5.4"],
        },
    )

    response = client.post(
        "/admin/newapi/upstream-credentials/sync",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["synced"] == 1
    assert body["failed"] == 0
    assert newapi.updated[-1]["group"] == "private-u-member"


def test_newapi_claude_bridge_endpoint_requires_internal_key_and_uses_credential() -> None:
    bridge = FakeOAuthBridgeExecutor()
    client = TestClient(
        create_app(
            settings=settings(newapi_sync_enabled=False),
            oidc_client=FakeOidcClient(),
            oauth_bridge_executor=bridge,
        )
    )
    token = issue_token(client)
    imported = client.post(
        "/me/upstream-credentials/claude-max/import",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": "claude-account-1",
            "access_token": "claude-access",
            "refresh_token": "claude-refresh",
            "scopes": ["user:inference"],
        },
    )
    credential_id = imported.json()["id"]

    denied = client.post(
        f"/bridge/upstreams/credentials/{credential_id}/anthropic/v1/messages",
        headers={"x-api-key": "wrong"},
        json={"model": "claude-max/claude-sonnet-4-6", "messages": []},
    )
    assert denied.status_code == 401

    response = client.post(
        f"/bridge/upstreams/credentials/{credential_id}/anthropic/v1/messages",
        headers={"x-api-key": "bridge-secret"},
        json={"model": "claude-max/claude-sonnet-4-6", "messages": []},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "claude-sonnet-4-6"
    assert bridge.calls == [
        ("anthropic_messages", "claude-sonnet-4-6", credential_id)
    ]


def test_newapi_codex_openai_bridge_endpoint_requires_internal_key_and_uses_credential() -> None:
    bridge = FakeCodexOAuthBridgeExecutor()
    client = TestClient(
        create_app(
            settings=settings(newapi_sync_enabled=False),
            oidc_client=FakeOidcClient(),
            oauth_bridge_executor=bridge,
        )
    )
    token = issue_token(client)
    imported = client.post(
        "/me/upstream-credentials/codex/import",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": "openai-account-1",
            "access_token": "codex-access",
            "refresh_token": "codex-refresh",
            "available_models": ["gpt-5.4"],
        },
    )
    credential_id = imported.json()["id"]

    denied = client.post(
        f"/bridge/upstreams/credentials/{credential_id}/openai/v1/chat/completions",
        headers={"x-api-key": "wrong"},
        json={"model": "gpt-5.4", "messages": []},
    )
    assert denied.status_code == 401

    response = client.post(
        f"/bridge/upstreams/credentials/{credential_id}/openai/v1/chat/completions",
        headers={"x-api-key": "bridge-secret"},
        json={"model": "gpt-5.4", "messages": []},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "gpt-5.4"
    assert bridge.calls == [("openai_chat", "gpt-5.4", credential_id)]


def test_newapi_codex_openai_bridge_endpoint_supports_responses() -> None:
    bridge = FakeCodexOAuthBridgeExecutor()
    client = TestClient(
        create_app(
            settings=settings(newapi_sync_enabled=False),
            oidc_client=FakeOidcClient(),
            oauth_bridge_executor=bridge,
        )
    )
    token = issue_token(client)
    imported = client.post(
        "/me/upstream-credentials/codex/import",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": "openai-account-1",
            "access_token": "codex-access",
            "refresh_token": "codex-refresh",
            "available_models": ["gpt-5.4"],
        },
    )
    credential_id = imported.json()["id"]

    response = client.post(
        f"/bridge/upstreams/credentials/{credential_id}/openai/v1/responses",
        headers={"x-api-key": "bridge-secret"},
        json={"model": "openai-codex/gpt-5.4", "input": "hello"},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "gpt-5.4"
    assert bridge.calls == [("openai_responses", "gpt-5.4", credential_id)]


def test_newapi_codex_openai_bridge_endpoint_supports_streaming_chat() -> None:
    bridge = FakeCodexOAuthBridgeExecutor()
    client = TestClient(
        create_app(
            settings=settings(newapi_sync_enabled=False),
            oidc_client=FakeOidcClient(),
            oauth_bridge_executor=bridge,
        )
    )
    token = issue_token(client)
    imported = client.post(
        "/me/upstream-credentials/codex/import",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": "openai-account-1",
            "access_token": "codex-access",
            "refresh_token": "codex-refresh",
            "available_models": ["gpt-5.4"],
        },
    )
    credential_id = imported.json()["id"]

    with client.stream(
        "POST",
        f"/bridge/upstreams/credentials/{credential_id}/openai/v1/chat/completions",
        headers={"x-api-key": "bridge-secret"},
        json={"model": "gpt-5.4", "messages": [], "stream": True},
    ) as response:
        body = b"".join(response.iter_bytes())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b'data: {"choices":[{"delta":{"content":"ok"}}]}' in body
    assert b"data: [DONE]" in body
    assert bridge.stream_calls == [("openai_chat", "gpt-5.4", credential_id)]


def test_newapi_claude_bridge_stream_primes_upstream_errors_before_200() -> None:
    client = TestClient(
        create_app(
            settings=settings(newapi_sync_enabled=False),
            oidc_client=FakeOidcClient(),
            oauth_bridge_executor=FailingStreamingOAuthBridgeExecutor(),
        )
    )
    token = issue_token(client)
    imported = client.post(
        "/me/upstream-credentials/claude-max/import",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": "claude-account-1",
            "access_token": "claude-access",
            "refresh_token": "claude-refresh",
            "scopes": ["user:inference"],
        },
    )
    credential_id = imported.json()["id"]

    response = client.post(
        f"/bridge/upstreams/credentials/{credential_id}/anthropic/v1/messages",
        headers={"x-api-key": "bridge-secret"},
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "upstream rejected sampling params"
