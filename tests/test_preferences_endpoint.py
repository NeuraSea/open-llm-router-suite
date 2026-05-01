"""Tests for GET /me/preferences and PATCH /me/preferences."""

from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
from enterprise_llm_proxy.config import AppSettings
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


def build_client() -> TestClient:
    return TestClient(
        create_app(
            settings=AppSettings(router_public_base_url="https://router.example.com/v1"),
            oidc_client=FakeOidcClient(),
        )
    )


def issue_token(client: TestClient, code: str) -> str:
    return client.post("/auth/oidc/callback", json={"code": code}).json()["access_token"]


def test_get_preferences_returns_defaults_when_none_set() -> None:
    client = build_client()
    token = issue_token(client, "member-code")

    response = client.get(
        "/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "u-member"
    assert payload["default_model"] is None
    assert payload["routing_config"] == {}


def test_patch_preferences_updates_default_model() -> None:
    client = build_client()
    token = issue_token(client, "member-code")

    response = client.patch(
        "/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={"default_model": "claude-opus-4-5"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_model"] == "claude-opus-4-5"
    assert payload["user_id"] == "u-member"


def test_patch_preferences_get_returns_updated_model() -> None:
    """PATCH persists so that subsequent GET returns the updated value."""
    client = build_client()
    token = issue_token(client, "member-code")

    client.patch(
        "/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={"default_model": "gpt-4o"},
    )

    get_response = client.get(
        "/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert get_response.status_code == 200
    assert get_response.json()["default_model"] == "gpt-4o"


def test_patch_preferences_updates_routing_config() -> None:
    client = build_client()
    token = issue_token(client, "member-code")

    response = client.patch(
        "/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={"routing_config": {"prefer_provider": "anthropic"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_config"] == {"prefer_provider": "anthropic"}


def test_patch_preferences_with_arbitrary_model_stores_it() -> None:
    """PATCH does not validate model names — it stores whatever is provided."""
    client = build_client()
    token = issue_token(client, "member-code")

    response = client.patch(
        "/me/preferences",
        headers={"Authorization": f"Bearer {token}"},
        json={"default_model": "not-a-real-model"},
    )

    assert response.status_code == 200
    assert response.json()["default_model"] == "not-a-real-model"


def test_preferences_are_isolated_per_user() -> None:
    """Two users have independent preferences."""
    client = build_client()
    admin_token = issue_token(client, "admin-code")
    member_token = issue_token(client, "member-code")

    client.patch(
        "/me/preferences",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"default_model": "admin-model"},
    )

    member_response = client.get(
        "/me/preferences",
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert member_response.json()["default_model"] is None


def test_preferences_require_authentication() -> None:
    client = build_client()

    response = client.get("/me/preferences")
    assert response.status_code == 401

    response = client.patch("/me/preferences", json={"default_model": "x"})
    assert response.status_code == 401
