from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.services.execution import ExecutionResult
from enterprise_llm_proxy.services.identity import OidcIdentity


class FakeOidcClient:
    def exchange_code(self, code: str) -> dict[str, str]:
        return {"access_token": code}

    def fetch_userinfo(self, access_token: str) -> OidcIdentity:
        if access_token == "member-code":
            return OidcIdentity(
                subject="u-member",
                email="member@example.com",
                name="Member",
                team_ids=["platform"],
                role="member",
            )
        return OidcIdentity(
            subject="u-admin",
            email="admin@example.com",
            name="Admin",
            team_ids=["platform"],
            role="admin",
        )


class FakeExecutor:
    def execute(self, request, credential) -> ExecutionResult:  # type: ignore[no-untyped-def]
        return ExecutionResult(
            body={"ok": True, "model": request.model, "credential_id": credential.id},
            tokens_in=1,
            tokens_out=1,
        )


def issue_token(client: TestClient, code: str) -> str:
    return client.post("/auth/oidc/callback", json={"code": code}).json()["access_token"]


def test_developer_can_generate_platform_api_key_and_use_it() -> None:
    client = TestClient(
        create_app(
            settings=AppSettings(router_public_base_url="https://router.example.com/v1"),
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeExecutor(),
            oauth_bridge_executor=FakeExecutor(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")
    client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "provider": "openai",
            "auth_kind": "api_key",
            "account_id": "acct-openai-1",
            "scopes": ["model:read"],
            "access_token": "provider-key",
            "max_concurrency": 2,
        },
    )
    client.post(
        "/admin/quotas",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"scope_type": "user", "scope_id": "u-member", "limit": 100},
    )

    key_response = client.post(
        "/developer/api-keys",
        headers={"Authorization": f"Bearer {member_token}"},
        json={"name": "MacBook Pro"},
    )

    assert key_response.status_code == 201
    api_key = key_response.json()["api_key"]
    assert api_key.startswith("elp_")

    response = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    assert response.status_code == 200


def test_routerctl_bootstrap_returns_install_command() -> None:
    client = TestClient(
        create_app(
            settings=AppSettings(router_public_base_url="https://router.example.com/v1"),
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeExecutor(),
            oauth_bridge_executor=FakeExecutor(),
        )
    )
    member_token = issue_token(client, "member-code")

    response = client.post(
        "/developer/bootstrap/routerctl",
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["bootstrap_token"]
    assert payload["expires_at"]
    assert 'ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN="' in payload["install_command"]
    assert 'export NO_PROXY="router.example.com,localhost,127.0.0.1"' in payload["install_command"]
    assert 'export no_proxy="$NO_PROXY"' in payload["install_command"]
    assert 'export ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN="' in payload["install_command"]
    assert "curl --noproxy router.example.com -fsSL https://router.example.com/install/routerctl.sh | bash" in payload["install_command"]
    assert payload["windows_install_command"].startswith(
        'powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol'
    )
    assert "[Net.ServicePointManager]::SecurityProtocol" in payload["windows_install_command"]
    assert "https://router.example.com/install/routerctl.ps1" in payload["windows_install_command"]
    assert "$env:no_proxy=$env:NO_PROXY;" in payload["windows_install_command"]
    assert "$env:ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN='" in payload["windows_install_command"]


def test_app_reuses_persisted_platform_api_key_across_app_recreation(postgres_database_url: str) -> None:
    settings = AppSettings(
        router_public_base_url="https://router.example.com/v1",
        database_url=postgres_database_url,
    )
    client = TestClient(
        create_app(
            settings=settings,
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeExecutor(),
            oauth_bridge_executor=FakeExecutor(),
        )
    )
    member_token = issue_token(client, "member-code")

    key_response = client.post(
        "/developer/api-keys",
        headers={"Authorization": f"Bearer {member_token}"},
        json={"name": "MacBook Pro"},
    )

    assert key_response.status_code == 201
    api_key = key_response.json()["api_key"]

    recreated_client = TestClient(
        create_app(
            settings=settings,
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeExecutor(),
            oauth_bridge_executor=FakeExecutor(),
        )
    )

    response = recreated_client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    assert response.status_code == 200
