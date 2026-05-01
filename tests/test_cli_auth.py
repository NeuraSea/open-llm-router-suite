from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app, _InMemoryCliAuthRepository
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.domain.credentials import (
    CredentialState,
    CredentialVisibility,
    ProviderCredential,
)
from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.services.execution import ExecutionResult
from enterprise_llm_proxy.services.identity import OidcIdentity
from enterprise_llm_proxy.services.model_catalog import ModelDefinition


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


class FakeExecutor:
    def execute(self, request, credential) -> ExecutionResult:  # type: ignore[no-untyped-def]
        return ExecutionResult(
            body={"ok": True, "protocol": request.protocol, "model": request.model},
            tokens_in=1,
            tokens_out=1,
        )


class FakeLMStudioService:
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
                id="zai-org/glm-4.7-flash",
                object="model",
                owned_by="openai_compat",
                provider="openai_compat",
                model_profile="zai-org/glm-4.7-flash",
                upstream_model="zai-org/glm-4.7-flash",
                display_name="GLM 4.7 Flash",
                supported_protocols=["openai_chat", "openai_responses", "openai_embeddings"],
                supported_clients=["codex"],
                auth_modes=["api_key"],
                description="via LM Studio",
            )
        ]

    def has_model(self, model_id: str) -> bool:
        return model_id == "zai-org/glm-4.7-flash"


class FakeBusyLMStudioService(FakeLMStudioService):
    def build_system_credential(self) -> ProviderCredential:
        return super().build_system_credential().replace(concurrent_leases=1)


def issue_token(client: TestClient, code: str) -> str:
    return client.post("/auth/oidc/callback", json={"code": code}).json()["access_token"]


def build_client(cli_auth_repository: _InMemoryCliAuthRepository | None = None) -> TestClient:
    return TestClient(
        create_app(
            settings=AppSettings(
                router_public_base_url="https://router.example.com/v1",
                feishu_client_id="cli_test_123",
                feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
                session_cookie_secure=False,
            ),
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeExecutor(),
            oauth_bridge_executor=FakeExecutor(),
            cli_auth_repository=cli_auth_repository,
        )
    )


def test_in_memory_cli_auth_repository_sweeps_expired_entries() -> None:
    repo = _InMemoryCliAuthRepository()
    now = datetime.now(UTC)

    repo.consume_jti(jti="expired-jti", expires_at=now - timedelta(minutes=5))
    repo.consume_jti(jti="fresh-jti", expires_at=now + timedelta(minutes=5))
    repo.put_pending_login(
        login_id="expired-login",
        payload={"principal_id": "u-expired"},
        expires_at=now - timedelta(minutes=5),
    )
    repo.put_pending_login(
        login_id="fresh-login",
        payload={"principal_id": "u-fresh"},
        expires_at=now + timedelta(minutes=5),
    )
    repo.put_pending_code(
        code="expired-code",
        payload={"principal_id": "u-expired"},
        expires_at=now - timedelta(minutes=5),
    )
    repo.put_pending_code(
        code="fresh-code",
        payload={"principal_id": "u-fresh"},
        expires_at=now + timedelta(minutes=5),
    )

    repo.sweep_expired()

    assert "expired-jti" not in repo._consumed_jtis
    assert "fresh-jti" in repo._consumed_jtis
    assert "expired-login" not in repo._pending_logins
    assert "fresh-login" in repo._pending_logins
    assert "expired-code" not in repo._pending_codes
    assert "fresh-code" in repo._pending_codes


def test_cli_auth_start_rejects_non_localhost_redirect_uri() -> None:
    client = build_client()
    member_token = issue_token(client, "member-code")

    response = client.post(
        "/cli/auth/start",
        json={
            "redirect_uri": "https://evil.com/callback",
            "state": "cli-state-1",
            "code_challenge": "challenge-abc",
        },
    )

    assert response.status_code == 400
    assert "redirect_uri must target localhost" in response.json()["detail"]


def test_cli_auth_browser_returns_404_for_unknown_login_id() -> None:
    client = build_client()

    response = client.get(
        "/cli/auth/browser?login_id=nonexistent",
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_cli_auth_exchange_returns_400_for_invalid_code() -> None:
    client = build_client()

    response = client.post(
        "/cli/auth/exchange",
        json={
            "code": "bogus-code-that-does-not-exist",
            "code_verifier": "some-verifier",
        },
    )

    assert response.status_code == 400
    assert "Invalid or expired CLI authorization code" in response.json()["detail"]


def test_cli_auth_exchange_returns_400_for_wrong_pkce_verifier() -> None:
    client = build_client()

    # Start the CLI auth flow (no auth required)
    start_response = client.post(
        "/cli/auth/start",
        json={
            "redirect_uri": "http://localhost:1455/callback",
            "state": "cli-state-x",
            "code_challenge": "aGVsbG8td29ybGQ",  # some challenge
        },
    )
    assert start_response.status_code == 200
    login_id = start_response.json()["login_id"]

    # Browser visits /cli/auth/browser → redirects to Feishu with state=cli:{login_id}
    browser_response = client.get(
        f"/cli/auth/browser?login_id={login_id}",
        follow_redirects=False,
    )
    assert browser_response.status_code == 303
    assert "accounts.feishu.cn" in browser_response.headers["location"]

    # Feishu OIDC callback completes the flow: principal is captured, code issued
    oidc_response = client.get(
        f"/auth/oidc/callback?code=member-code&state=cli:{login_id}",
        follow_redirects=False,
    )
    assert oidc_response.status_code == 303
    location = oidc_response.headers["location"]
    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    code = params["code"][0]

    # Exchange with wrong verifier
    exchange_response = client.post(
        "/cli/auth/exchange",
        json={
            "code": code,
            "code_verifier": "wrong-verifier-that-does-not-match",
        },
    )

    assert exchange_response.status_code == 400
    assert "PKCE validation failed" in exchange_response.json()["detail"]


def test_cli_bootstrap_exchange_rejects_wrong_token_kind() -> None:
    client = build_client()
    # Issue a human_session token (not bootstrap_install)
    member_token = issue_token(client, "member-code")

    response = client.post(
        "/cli/bootstrap/exchange",
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert response.status_code == 403
    assert "Bootstrap token required" in response.json()["detail"]


def test_cli_bootstrap_exchange_returns_cli_session_with_principal() -> None:
    client = build_client()
    member_token = issue_token(client, "member-code")
    bootstrap_response = client.post(
        "/developer/bootstrap/routerctl",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert bootstrap_response.status_code == 201
    bootstrap_token = bootstrap_response.json()["bootstrap_token"]

    response = client.post(
        "/cli/bootstrap/exchange",
        headers={"Authorization": f"Bearer {bootstrap_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["expires_at"]
    assert payload["principal"]["email"] == "member@example.com"


def test_cli_activate_rejects_non_cli_session_token() -> None:
    client = build_client()

    # Get a bootstrap token
    member_token = issue_token(client, "member-code")
    bootstrap_response = client.post(
        "/developer/bootstrap/routerctl",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert bootstrap_response.status_code == 201
    bootstrap_token = bootstrap_response.json()["bootstrap_token"]

    # Try to use bootstrap token directly for /cli/activate (not cli_session)
    response = client.post(
        "/cli/activate",
        headers={"Authorization": f"Bearer {bootstrap_token}"},
        json={"client": "claude-code", "model": "claude-sonnet-4-20250514"},
    )

    assert response.status_code == 403
    assert "CLI session required" in response.json()["detail"]


def test_cli_activate_uses_client_specific_default_models() -> None:
    client = build_client()
    member_token = issue_token(client, "member-code")
    bootstrap_response = client.post(
        "/developer/bootstrap/routerctl",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    bootstrap_token = bootstrap_response.json()["bootstrap_token"]
    exchange_response = client.post(
        "/cli/bootstrap/exchange",
        headers={"Authorization": f"Bearer {bootstrap_token}"},
    )
    cli_session_token = exchange_response.json()["access_token"]

    claude_response = client.post(
        "/cli/activate",
        headers={"Authorization": f"Bearer {cli_session_token}"},
        json={"client": "claude-code", "model": ""},
    )
    codex_response = client.post(
        "/cli/activate",
        headers={"Authorization": f"Bearer {cli_session_token}"},
        json={"client": "codex", "model": ""},
    )

    assert claude_response.status_code == 200
    assert claude_response.json()["model"] == "claude-max/claude-sonnet-4-6"
    assert codex_response.status_code == 200
    assert codex_response.json()["model"] == "openai-codex/gpt-5.4"


def test_cli_models_requires_cli_session_token() -> None:
    client = build_client()
    member_token = issue_token(client, "member-code")

    response = client.get(
        "/cli/models",
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert response.status_code == 403
    assert "CLI session required" in response.json()["detail"]


def test_cli_models_returns_only_models_with_live_routes() -> None:
    client = TestClient(
        create_app(
            settings=AppSettings(
                router_public_base_url="https://router.example.com/v1",
                feishu_client_id="cli_test_123",
                feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
                session_cookie_secure=False,
            ),
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeExecutor(),
            oauth_bridge_executor=FakeExecutor(),
            cli_auth_repository=_InMemoryCliAuthRepository(),
            lmstudio_service=FakeLMStudioService(),
        )
    )
    member_token = issue_token(client, "member-code")
    bootstrap_response = client.post(
        "/developer/bootstrap/routerctl",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    bootstrap_token = bootstrap_response.json()["bootstrap_token"]
    exchange_response = client.post(
        "/cli/bootstrap/exchange",
        headers={"Authorization": f"Bearer {bootstrap_token}"},
    )
    cli_session_token = exchange_response.json()["access_token"]

    response = client.get(
        "/cli/models",
        headers={"Authorization": f"Bearer {cli_session_token}"},
    )

    assert response.status_code == 200
    models = response.json()["data"]
    ids = {item["id"] for item in models}
    assert "zai-org/glm-4.7-flash" in ids
    assert "openai/gpt-4.1" not in ids


def test_cli_models_includes_saturated_models_with_unavailable_reason() -> None:
    client = TestClient(
        create_app(
            settings=AppSettings(
                router_public_base_url="https://router.example.com/v1",
                feishu_client_id="cli_test_123",
                feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
                session_cookie_secure=False,
            ),
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeExecutor(),
            oauth_bridge_executor=FakeExecutor(),
            cli_auth_repository=_InMemoryCliAuthRepository(),
            lmstudio_service=FakeBusyLMStudioService(),
        )
    )
    member_token = issue_token(client, "member-code")
    bootstrap_response = client.post(
        "/developer/bootstrap/routerctl",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    bootstrap_token = bootstrap_response.json()["bootstrap_token"]
    exchange_response = client.post(
        "/cli/bootstrap/exchange",
        headers={"Authorization": f"Bearer {bootstrap_token}"},
    )
    cli_session_token = exchange_response.json()["access_token"]

    response = client.get(
        "/cli/models",
        headers={"Authorization": f"Bearer {cli_session_token}"},
    )

    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()["data"]}
    assert by_id["zai-org/glm-4.7-flash"]["routable"] is False
    assert "busy" in by_id["zai-org/glm-4.7-flash"]["unavailable_reason"]
