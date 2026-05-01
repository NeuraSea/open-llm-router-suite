"""Tests for GET /me/api-keys and DELETE /me/api-keys/{id}."""

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


def issue_token(client: TestClient, code: str = "member-code") -> str:
    return client.post("/auth/oidc/callback", json={"code": code}).json()["access_token"]


def create_api_key(client: TestClient, token: str, name: str = "My Key") -> dict:
    response = client.post(
        "/developer/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()


# ---------------------------------------------------------------------------
# GET /me/api-keys
# ---------------------------------------------------------------------------


def test_list_api_keys_returns_empty_initially() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.get("/me/api-keys", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert "data" in payload
    assert payload["data"] == []


def test_list_api_keys_returns_created_key() -> None:
    client = build_client()
    token = issue_token(client)
    created = create_api_key(client, token, name="Laptop Key")

    response = client.get("/me/api-keys", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    items = response.json()["data"]
    assert len(items) == 1
    assert items[0]["id"] == created["id"]
    assert items[0]["name"] == "Laptop Key"


def test_list_api_keys_does_not_expose_raw_secret() -> None:
    """The list endpoint should expose key_prefix but not the full api_key secret."""
    client = build_client()
    token = issue_token(client)
    create_api_key(client, token)

    response = client.get("/me/api-keys", headers={"Authorization": f"Bearer {token}"})

    items = response.json()["data"]
    assert len(items) == 1
    item = items[0]
    # key_prefix should be present (safe to show)
    assert "key_prefix" in item
    # The full secret api_key should NOT be present in the list response
    assert "api_key" not in item


def test_list_api_keys_isolated_per_user() -> None:
    """Keys created by one user are not visible to another user."""
    client = build_client()
    member_token = issue_token(client, "member-code")
    admin_token = issue_token(client, "admin-code")

    create_api_key(client, member_token, name="Member Key")

    admin_response = client.get("/me/api-keys", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_response.json()["data"] == []


def test_list_api_keys_requires_authentication() -> None:
    client = build_client()
    response = client.get("/me/api-keys")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /me/api-keys/{id}
# ---------------------------------------------------------------------------


def test_delete_api_key_removes_it_from_list() -> None:
    client = build_client()
    token = issue_token(client)
    created = create_api_key(client, token)
    key_id = created["id"]

    delete_response = client.delete(
        f"/me/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_response.status_code == 204

    list_response = client.get("/me/api-keys", headers={"Authorization": f"Bearer {token}"})
    assert list_response.json()["data"] == []


def test_delete_nonexistent_key_returns_404() -> None:
    client = build_client()
    token = issue_token(client)

    response = client.delete(
        "/me/api-keys/nonexistent-id",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_delete_another_users_key_returns_404() -> None:
    """A user cannot delete a key that belongs to someone else."""
    client = build_client()
    member_token = issue_token(client, "member-code")
    admin_token = issue_token(client, "admin-code")

    created = create_api_key(client, member_token)
    key_id = created["id"]

    response = client.delete(
        f"/me/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


def test_delete_key_multiple_times_returns_404_on_second() -> None:
    client = build_client()
    token = issue_token(client)
    created = create_api_key(client, token)
    key_id = created["id"]

    first = client.delete(f"/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    assert first.status_code == 204

    second = client.delete(f"/me/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    assert second.status_code == 404


def test_delete_api_key_requires_authentication() -> None:
    client = build_client()
    response = client.delete("/me/api-keys/some-id")
    assert response.status_code == 401
