"""Tests for /me/usage/activity, /me/usage/activity/by-model, and /me/usage/logs."""

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


# ---------------------------------------------------------------------------
# /me/usage/activity
# ---------------------------------------------------------------------------


def test_activity_returns_expected_structure() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get(
        "/me/usage/activity",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "data" in payload
    assert "period" in payload
    assert isinstance(payload["data"], list)


def test_activity_default_period_is_7d() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get(
        "/me/usage/activity",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["period"] == "7d"


def test_activity_with_period_30d() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get(
        "/me/usage/activity?period=30d",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["period"] == "30d"
    assert isinstance(payload["data"], list)


def test_activity_with_custom_period() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get(
        "/me/usage/activity?period=14d",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["period"] == "14d"


def test_activity_requires_authentication() -> None:
    client = build_client()
    response = client.get("/me/usage/activity")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# /me/usage/activity/by-model
# ---------------------------------------------------------------------------


def test_activity_by_model_returns_data_list() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get(
        "/me/usage/activity/by-model",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "data" in payload
    assert isinstance(payload["data"], list)


def test_activity_by_model_accepts_days_param() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get(
        "/me/usage/activity/by-model?days=30",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert "data" in response.json()


def test_activity_by_model_requires_authentication() -> None:
    client = build_client()
    response = client.get("/me/usage/activity/by-model")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# /me/usage/logs
# ---------------------------------------------------------------------------


def test_logs_returns_expected_structure() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get(
        "/me/usage/logs",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "data" in payload
    assert "page" in payload
    assert "page_size" in payload
    assert isinstance(payload["data"], list)


def test_logs_default_pagination() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get(
        "/me/usage/logs",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 50


def test_logs_with_page_param() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get(
        "/me/usage/logs?page=2",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 2
    assert payload["page_size"] == 50


def test_logs_with_page_size_param() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get(
        "/me/usage/logs?page=1&page_size=10",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 10


def test_logs_requires_authentication() -> None:
    client = build_client()
    response = client.get("/me/usage/logs")
    assert response.status_code == 401
