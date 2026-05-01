from __future__ import annotations

from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import (
    create_app,
    _InMemoryCliAuthRepository,
)
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.repositories.cli_auth import _InMemoryRevokedTokenRepository
from enterprise_llm_proxy.repositories.issued_tokens import _InMemoryIssuedTokenRepository
from enterprise_llm_proxy.services.execution import ExecutionResult
from enterprise_llm_proxy.services.identity import OidcIdentity


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


def build_client(
    cli_auth_repository: _InMemoryCliAuthRepository | None = None,
    issued_token_repo: _InMemoryIssuedTokenRepository | None = None,
    revoked_token_repo: _InMemoryRevokedTokenRepository | None = None,
) -> TestClient:
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
            issued_token_repo=issued_token_repo,
            revoked_token_repo=revoked_token_repo,
        )
    )


def issue_human_token(client: TestClient, code: str) -> str:
    return client.post("/auth/oidc/callback", json={"code": code}).json()["access_token"]


def get_bootstrap_token(client: TestClient, human_token: str) -> str:
    resp = client.post(
        "/developer/bootstrap/routerctl",
        headers={"Authorization": f"Bearer {human_token}"},
    )
    assert resp.status_code == 201
    return resp.json()["bootstrap_token"]


def get_cli_session_token(client: TestClient, bootstrap_token: str) -> str:
    resp = client.post(
        "/cli/bootstrap/exchange",
        headers={"Authorization": f"Bearer {bootstrap_token}"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def get_client_access_token(client: TestClient, cli_session_token: str) -> dict:
    resp = client.post(
        "/cli/activate",
        headers={"Authorization": f"Bearer {cli_session_token}"},
        json={"client": "claude-code", "model": "claude-sonnet-4-20250514"},
    )
    assert resp.status_code == 200
    return resp.json()


# ---- Tests ----


def test_cli_session_appears_in_sessions_list() -> None:
    issued_repo = _InMemoryIssuedTokenRepository()
    client = build_client(issued_token_repo=issued_repo)

    admin_token = issue_human_token(client, "admin-code")
    bootstrap_token = get_bootstrap_token(client, admin_token)
    cli_session_token = get_cli_session_token(client, bootstrap_token)
    del cli_session_token  # noqa: just ensuring the token was issued

    resp = client.get(
        "/admin/cli/sessions",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    session = data[0]
    assert session["email"] == "admin@example.com"
    assert session["kind"] == "cli_session"
    assert "jti" in session
    assert "issued_at" in session
    assert "expires_at" in session
    assert session["is_revoked"] is False


def test_client_access_appears_in_activations() -> None:
    issued_repo = _InMemoryIssuedTokenRepository()
    client = build_client(issued_token_repo=issued_repo)

    admin_token = issue_human_token(client, "admin-code")
    bootstrap_token = get_bootstrap_token(client, admin_token)
    cli_session_token = get_cli_session_token(client, bootstrap_token)
    activation = get_client_access_token(client, cli_session_token)
    del activation

    resp = client.get(
        "/admin/cli/activations",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    record = data[0]
    assert record["email"] == "admin@example.com"
    assert record["kind"] == "client_access"
    assert record["client"] == "claude_code"
    assert record["model"] == "claude-sonnet-4-20250514"
    assert record["is_revoked"] is False


def test_admin_can_revoke_token() -> None:
    issued_repo = _InMemoryIssuedTokenRepository()
    revoked_repo = _InMemoryRevokedTokenRepository()
    client = build_client(issued_token_repo=issued_repo, revoked_token_repo=revoked_repo)

    admin_token = issue_human_token(client, "admin-code")
    bootstrap_token = get_bootstrap_token(client, admin_token)
    cli_session_token = get_cli_session_token(client, bootstrap_token)
    del cli_session_token

    # Get the session list and grab the jti
    sessions_resp = client.get(
        "/admin/cli/sessions",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert sessions_resp.status_code == 200
    data = sessions_resp.json()["data"]
    assert len(data) == 1
    jti = data[0]["jti"]

    # Revoke the token
    revoke_resp = client.post(
        f"/admin/cli/revoke/{jti}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "revoked"
    assert revoke_resp.json()["jti"] == jti

    # Verify it now shows as revoked
    sessions_resp2 = client.get(
        "/admin/cli/sessions",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    data2 = sessions_resp2.json()["data"]
    assert len(data2) == 1
    assert data2[0]["is_revoked"] is True


def test_non_admin_cannot_list_sessions() -> None:
    client = build_client()

    member_token = issue_human_token(client, "member-code")
    resp = client.get(
        "/admin/cli/sessions",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403


def test_non_admin_cannot_list_activations() -> None:
    client = build_client()

    member_token = issue_human_token(client, "member-code")
    resp = client.get(
        "/admin/cli/activations",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403


def test_non_admin_cannot_revoke_token() -> None:
    client = build_client()

    member_token = issue_human_token(client, "member-code")
    resp = client.post(
        "/admin/cli/revoke/some-jti",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403
