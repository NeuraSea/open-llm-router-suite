import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.services.execution import ExecutionResult
from enterprise_llm_proxy.services.identity import OidcIdentity
from enterprise_llm_proxy.services.routerctl_distribution import RouterctlDistributionService


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
            body={"ok": True},
            tokens_in=1,
            tokens_out=1,
        )


def _fake_distribution_service() -> RouterctlDistributionService:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "enterprise_llm_proxy-0.1.0-py3-none-any.whl").touch()
    return RouterctlDistributionService(wheel_dir=tmp)


def build_client() -> TestClient:
    return TestClient(
        create_app(
            settings=AppSettings(
                feishu_client_id="cli_test_123",
                feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
                router_public_base_url="https://router.example.com/v1",
                session_cookie_secure=False,
            ),
            oidc_client=FakeOidcClient(),
            litellm_executor=FakeExecutor(),
            oauth_bridge_executor=FakeExecutor(),
            distribution_service=_fake_distribution_service(),
        )
    )


def issue_admin_session(client: TestClient) -> None:
    response = client.get("/auth/oidc/callback?code=admin-code", follow_redirects=False)
    assert response.status_code == 303


def test_launch_page_renders_feishu_entrypoint() -> None:
    client = build_client()

    response = client.get("/feishu/launch")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert "企业级 LLM Router 控制台" in response.text


def test_browser_callback_sets_cookie_and_redirects_to_portal() -> None:
    client = build_client()

    response = client.get("/auth/oidc/callback?code=member-code", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/portal"
    assert "router_session=" in response.headers["set-cookie"]


def test_portal_serves_spa_shell_for_anonymous_user() -> None:
    client = build_client()

    response = client.get("/portal", follow_redirects=False)

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text


def test_portal_renders_developer_access_page_for_logged_in_user() -> None:
    client = build_client()
    client.get("/auth/oidc/callback?code=member-code", follow_redirects=False)

    response = client.get("/portal")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text


def test_portal_admin_route_serves_spa_shell() -> None:
    client = build_client()

    response = client.get("/portal/admin/credentials")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text


def test_cookie_session_can_call_developer_api() -> None:
    client = build_client()
    client.get("/auth/oidc/callback?code=member-code", follow_redirects=False)

    response = client.post("/developer/api-keys", json={"name": "Browser session key"})

    assert response.status_code == 201
    assert response.json()["api_key"].startswith("elp_")


def test_ui_config_returns_frontend_bootstrap_settings() -> None:
    client = build_client()

    response = client.get("/ui/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["router_public_base_url"] == "https://router.example.com/v1"
    assert payload["default_claude_model"] == "claude-max/claude-sonnet-4-6"
    assert payload["default_codex_model"] == "openai-codex/gpt-5.4"
    assert payload["router_control_plane_base_url"] == "https://router.example.com"
    assert payload["routerctl_install_url"] == "https://router.example.com/install/routerctl.sh"
    assert payload["routerctl_windows_install_url"] == "https://router.example.com/install/routerctl.ps1"
    assert payload["codex_oauth_browser_enabled"] is False
    assert payload["feishu_authorize_url"].startswith(
        "https://accounts.feishu.cn/open-apis/authen/v1/authorize?client_id=cli_test_123"
    )


def test_routerctl_install_script_endpoint_is_available() -> None:
    client = build_client()

    response = client.get("/install/routerctl.sh")
    powershell_response = client.get("/install/routerctl.ps1")

    assert response.status_code == 200
    assert 'export NO_PROXY="router.example.com,localhost,127.0.0.1"' in response.text
    assert 'export no_proxy="$NO_PROXY"' in response.text
    assert "uv --native-tls tool install --force --from" in response.text
    assert "routerctl auth bootstrap" in response.text
    assert "routerctl codex bind" in response.text

    assert powershell_response.status_code == 200
    assert '$env:NO_PROXY = "router.example.com,localhost,127.0.0.1"' in powershell_response.text
    assert "$env:no_proxy = $env:NO_PROXY" in powershell_response.text
    assert '$env:ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN' in powershell_response.text
    assert 'uv --native-tls tool install --force --from "$WheelUrl" enterprise-llm-proxy' in powershell_response.text
    assert '--router-base-url "$RouterBaseUrl"' in powershell_response.text
    assert '--bootstrap-token "$BootstrapToken"' in powershell_response.text
    assert "routerctl codex bind" in powershell_response.text


def test_ui_models_returns_capability_filtered_model_catalog() -> None:
    client = build_client()

    response = client.get("/ui/models")

    assert response.status_code == 200
    payload = response.json()["data"]
    by_id = {item["id"]: item for item in payload}
    assert "openai-codex/gpt-5.4" in by_id
    assert by_id["openai-codex/gpt-5.4"]["supported_clients"] == ["claude_code", "codex"]
    assert by_id["openai-codex/gpt-5.4"]["provider"] == "openai-codex"
    assert "anthropic_messages" in by_id["openai-codex/gpt-5.4"]["supported_protocols"]
    assert "claude_code" in by_id["claude-max/claude-sonnet-4-20250514"]["supported_clients"]


def test_ui_session_requires_authentication() -> None:
    client = build_client()

    response = client.get("/ui/session")

    assert response.status_code == 401


def test_ui_session_returns_principal_for_cookie_session() -> None:
    client = build_client()
    client.get("/auth/oidc/callback?code=member-code", follow_redirects=False)

    response = client.get("/ui/session")

    assert response.status_code == 200
    assert response.json()["email"] == "member@example.com"
    assert response.json()["role"] == "member"
