"""Tests for the Codex ChatGPT OAuth portal flow.

The flow:
  1. User calls POST /me/upstream-credentials/codex-oauth/start → gets authorize_url + state
  2. User visits authorize_url; provider redirects to GET /auth/upstream/codex/callback?code=X&state=Y
  3. Server exchanges code, stores credential, redirects to /portal

State is now stored in the CLI auth repository (DB-backed or in-memory), not an in-memory dict,
so it survives across requests and works in multi-process deployments.
"""

import tempfile
from pathlib import Path
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import _InMemoryCliAuthRepository, create_app
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.services.identity import OidcIdentity
from enterprise_llm_proxy.services.routerctl_distribution import RouterctlDistributionService
from enterprise_llm_proxy.services.upstream_oauth import OAuthFlowStart, UpstreamOAuthIdentity


class FakeOidcClient:
    def exchange_code(self, code: str) -> dict[str, str]:
        return {"access_token": code}

    def fetch_userinfo(self, access_token: str) -> OidcIdentity:
        return OidcIdentity(
            subject="u-member",
            email="member@example.com",
            name="Member",
            team_ids=["platform"],
            role="member",
        )


class FakeCodexOAuthBroker:
    """Simulates the Codex OAuth broker without network calls."""

    def start(self, principal):  # type: ignore[no-untyped-def]
        return OAuthFlowStart(
            authorize_url="https://chatgpt.com/authorize?state=test-state-123",
            state="test-state-123",
        )

    def finish(self, *, code: str, state: str, principal):  # type: ignore[no-untyped-def]
        return UpstreamOAuthIdentity(
            subject="codex-user-456",
            email="member@example.com",
            name="Member",
            access_token="tok_fake",
            refresh_token=None,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=["openai"],
        )

    def refresh(self, refresh_token):  # type: ignore[no-untyped-def]
        return {}


def _fake_distribution_service() -> RouterctlDistributionService:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "enterprise_llm_proxy-0.1.0-py3-none-any.whl").touch()
    return RouterctlDistributionService(wheel_dir=tmp)


def build_client(
    cli_auth_repository=None,
) -> TestClient:
    return TestClient(
        create_app(
            settings=AppSettings(
                feishu_client_id="cli_test_123",
                feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
                router_public_base_url="https://router.example.com/v1",
                session_cookie_secure=False,
            ),
            oidc_client=FakeOidcClient(),
            codex_oauth_broker=FakeCodexOAuthBroker(),
            distribution_service=_fake_distribution_service(),
            cli_auth_repository=cli_auth_repository,
        ),
        follow_redirects=False,
    )


def login(client: TestClient) -> None:
    """Issue a session cookie by going through the OIDC login flow."""
    r = client.get("/auth/oidc/callback?code=member-code", follow_redirects=False)
    assert r.status_code == 303


# --- Cycle 1: state survives from start → callback ---


def test_codex_oauth_state_survives_to_callback() -> None:
    """State stored during /start is retrievable and consumed in /callback."""
    client = build_client()
    login(client)

    # Start the OAuth flow
    r = client.post("/me/upstream-credentials/codex-oauth/start")
    assert r.status_code == 200
    data = r.json()
    assert "state" in data
    state = data["state"]

    # Simulate provider callback
    r = client.get(f"/auth/upstream/codex/callback?code=fake-code&state={state}")
    assert r.status_code == 303  # redirect to /portal


# --- Cycle 2: second callback with same state returns 400 ---


def test_codex_oauth_callback_is_atomic() -> None:
    """State is consumed on first callback; a second callback with same state returns 400."""
    client = build_client()
    login(client)

    r = client.post("/me/upstream-credentials/codex-oauth/start")
    assert r.status_code == 200
    state = r.json()["state"]

    # First callback succeeds
    r1 = client.get(f"/auth/upstream/codex/callback?code=fake-code&state={state}")
    assert r1.status_code == 303

    # Second callback with same state must fail
    r2 = client.get(f"/auth/upstream/codex/callback?code=fake-code&state={state}")
    assert r2.status_code == 400
    assert "state" in r2.json()["detail"].lower() or "expired" in r2.json()["detail"].lower()


# --- Cycle 3: expired state returns 400 ---


def test_codex_oauth_expired_state_returns_400() -> None:
    """State that has expired is rejected at callback time."""
    cli_auth_repo = _InMemoryCliAuthRepository()
    client = build_client(cli_auth_repository=cli_auth_repo)
    login(client)

    # Manually insert an already-expired entry
    from enterprise_llm_proxy.domain.models import Principal

    expired_principal = Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )
    cli_auth_repo.put_codex_oauth_principal(
        state="expired-state-xyz",
        principal=expired_principal,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),  # already expired
    )

    r = client.get("/auth/upstream/codex/callback?code=fake-code&state=expired-state-xyz")
    assert r.status_code == 400
    assert "state" in r.json()["detail"].lower() or "expired" in r.json()["detail"].lower()


# --- Callback with unknown state returns 400 ---


def test_codex_oauth_unknown_state_returns_400() -> None:
    """Callback with a state that was never registered returns 400."""
    client = build_client()
    login(client)

    r = client.get("/auth/upstream/codex/callback?code=fake-code&state=nonexistent-state")
    assert r.status_code == 400
