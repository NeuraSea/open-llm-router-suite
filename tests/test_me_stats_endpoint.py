"""Tests for the GET /me/stats endpoint."""

from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.services.identity import OidcIdentity


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


def build_client() -> TestClient:
    return TestClient(
        create_app(
            settings=AppSettings(router_public_base_url="https://router.example.com/v1"),
            oidc_client=FakeOidcClient(),
        )
    )


def issue_token(client: TestClient) -> str:
    return client.post("/auth/oidc/callback", json={"code": "member-code"}).json()["access_token"]


def test_stats_requires_authentication() -> None:
    client = build_client()
    response = client.get("/me/stats")
    assert response.status_code == 401


def test_stats_returns_zeros_with_no_usage_data() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get("/me/stats", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["requests_this_month"] == 0
    assert payload["tokens_this_month"] == 0
    assert payload["active_api_keys"] == 0


def test_stats_active_api_keys_increments_after_key_creation() -> None:
    client = build_client()
    token = issue_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # Baseline: no keys yet
    before = client.get("/me/stats", headers=headers).json()
    assert before["active_api_keys"] == 0

    # Create an API key
    create_resp = client.post(
        "/developer/api-keys",
        json={"name": "Test key"},
        headers=headers,
    )
    assert create_resp.status_code == 201

    # Count should now be 1
    after = client.get("/me/stats", headers=headers).json()
    assert after["active_api_keys"] == 1


def test_stats_response_has_correct_shape() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get("/me/stats", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"requests_this_month", "tokens_this_month", "active_api_keys"}
    assert isinstance(payload["requests_this_month"], int)
    assert isinstance(payload["tokens_this_month"], int)
    assert isinstance(payload["active_api_keys"], int)
