"""Tests for server-side token revocation.

Behaviors:
1. POST /auth/server-logout returns 200 with a valid token
2. After logout, the same token is rejected with 401
3. A different (non-revoked) token still works normally
4. Logout with an invalid token is a no-op (returns 200, no crash)
"""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import _InMemoryRevokedTokenRepository, create_app
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.services.identity import OidcIdentity
from enterprise_llm_proxy.services.routerctl_distribution import RouterctlDistributionService


class FakeOidcClient:
    def exchange_code(self, code: str) -> dict[str, str]:
        return {"access_token": code}

    def fetch_userinfo(self, access_token: str) -> OidcIdentity:
        return OidcIdentity(
            subject=f"u-{access_token}",
            email=f"{access_token}@example.com",
            name=access_token.capitalize(),
            team_ids=["platform"],
            role="member",
        )


def _fake_distribution_service() -> RouterctlDistributionService:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "enterprise_llm_proxy-0.1.0-py3-none-any.whl").touch()
    return RouterctlDistributionService(wheel_dir=tmp)


def build_client(revoked_token_repo=None) -> TestClient:
    return TestClient(
        create_app(
            settings=AppSettings(
                feishu_client_id="cli_test_123",
                feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
                router_public_base_url="https://router.example.com/v1",
                session_cookie_secure=False,
            ),
            oidc_client=FakeOidcClient(),
            distribution_service=_fake_distribution_service(),
            revoked_token_repo=revoked_token_repo,
        ),
        follow_redirects=False,
    )


def _get_token(client: TestClient, code: str = "alice") -> str:
    """Log in and return the session token from the cookie."""
    r = client.get(f"/auth/oidc/callback?code={code}", follow_redirects=False)
    assert r.status_code == 303
    token = client.cookies.get("router_session")
    assert token is not None
    return token


# --- Cycle 1: server logout returns 200 ---


def test_server_logout_returns_200() -> None:
    client = build_client()
    _get_token(client)  # sets session cookie
    r = client.post("/auth/server-logout")
    assert r.status_code == 200
    assert r.json()["status"] == "logged out"


# --- Cycle 2: revoked token is rejected ---


def test_revoked_token_returns_401_on_next_request() -> None:
    revoke_repo = _InMemoryRevokedTokenRepository()
    client = build_client(revoked_token_repo=revoke_repo)
    _get_token(client)

    # Revoke the token
    r = client.post("/auth/server-logout")
    assert r.status_code == 200

    # Same token (still in cookie) is now rejected
    r = client.get("/ui/session")
    assert r.status_code == 401


# --- Cycle 3: non-revoked token still works ---


def test_valid_token_passes_after_other_token_revoked() -> None:
    revoke_repo = _InMemoryRevokedTokenRepository()
    client_alice = build_client(revoked_token_repo=revoke_repo)
    client_bob = build_client(revoked_token_repo=revoke_repo)

    _get_token(client_alice, code="alice")
    _get_token(client_bob, code="bob")

    # Alice logs out server-side
    r = client_alice.post("/auth/server-logout")
    assert r.status_code == 200

    # Bob's session still works
    r = client_bob.get("/ui/session")
    assert r.status_code == 200


# --- Cycle 4: logout with invalid token is a no-op ---


def test_server_logout_with_invalid_token_returns_200() -> None:
    client = build_client()
    r = client.post(
        "/auth/server-logout",
        headers={"Authorization": "Bearer not-a-valid-jwt"},
    )
    assert r.status_code == 200
