"""Tests for /admin/models CRUD endpoints.

These endpoints require a real database (session_factory) because they use
session_factory directly rather than an in-memory fallback. Tests that exercise
the full CRUD cycle use the postgres_database_url fixture and are skipped when
Postgres is unavailable.

Tests that only verify authorization (403 for non-admins, 503 without DB) run
against the in-memory app and do not require Postgres.
"""

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


def build_client(database_url: str | None = None) -> TestClient:
    settings = AppSettings(
        router_public_base_url="https://router.example.com/v1",
        database_url=database_url or "",
    )
    return TestClient(create_app(settings=settings, oidc_client=FakeOidcClient()))


def issue_token(client: TestClient, code: str) -> str:
    return client.post("/auth/oidc/callback", json={"code": code}).json()["access_token"]


_SAMPLE_MODEL = {
    "id": "custom/my-model",
    "display_name": "My Custom Model",
    "provider": "openai",
    "model_profile": "gpt",
    "upstream_model": "gpt-4o",
    "description": "A test model",
    "auth_modes": ["api_key"],
    "supported_clients": ["openai_sdk"],
    "enabled": True,
}


# ---------------------------------------------------------------------------
# Authorization tests (no DB needed)
# ---------------------------------------------------------------------------


def test_non_admin_gets_403_on_list_models() -> None:
    client = build_client()
    token = issue_token(client, "member-code")
    response = client.get("/admin/models", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_non_admin_gets_403_on_create_model() -> None:
    client = build_client()
    token = issue_token(client, "member-code")
    response = client.post(
        "/admin/models",
        headers={"Authorization": f"Bearer {token}"},
        json=_SAMPLE_MODEL,
    )
    assert response.status_code == 403


def test_non_admin_gets_403_on_patch_model() -> None:
    client = build_client()
    token = issue_token(client, "member-code")
    response = client.patch(
        "/admin/models/custom/my-model",
        headers={"Authorization": f"Bearer {token}"},
        json={"display_name": "Updated"},
    )
    assert response.status_code == 403


def test_non_admin_gets_403_on_delete_model() -> None:
    client = build_client()
    token = issue_token(client, "member-code")
    response = client.delete(
        "/admin/models/custom/my-model",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_admin_list_models_returns_empty_without_db() -> None:
    """GET /admin/models returns an empty list when no database is configured."""
    client = build_client()
    token = issue_token(client, "admin-code")
    response = client.get("/admin/models", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"data": []}


def test_admin_create_model_returns_503_without_db() -> None:
    """POST /admin/models returns 503 when no database is configured."""
    client = build_client()
    token = issue_token(client, "admin-code")
    response = client.post(
        "/admin/models",
        headers={"Authorization": f"Bearer {token}"},
        json=_SAMPLE_MODEL,
    )
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# Full CRUD tests (require Postgres)
# ---------------------------------------------------------------------------


def test_admin_can_create_and_list_custom_model(postgres_database_url: str) -> None:
    client = build_client(database_url=postgres_database_url)
    token = issue_token(client, "admin-code")

    create_response = client.post(
        "/admin/models",
        headers={"Authorization": f"Bearer {token}"},
        json=_SAMPLE_MODEL,
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["id"] == "custom/my-model"
    assert created["display_name"] == "My Custom Model"
    assert created["provider"] == "openai"
    assert created["enabled"] is True

    list_response = client.get("/admin/models", headers={"Authorization": f"Bearer {token}"})
    assert list_response.status_code == 200
    items = list_response.json()["data"]
    assert len(items) >= 1
    ids = [item["id"] for item in items]
    assert "custom/my-model" in ids


def test_admin_can_patch_custom_model(postgres_database_url: str) -> None:
    client = build_client(database_url=postgres_database_url)
    token = issue_token(client, "admin-code")

    client.post(
        "/admin/models",
        headers={"Authorization": f"Bearer {token}"},
        json={**_SAMPLE_MODEL, "id": "custom/patch-target"},
    )

    patch_response = client.patch(
        "/admin/models/custom/patch-target",
        headers={"Authorization": f"Bearer {token}"},
        json={"display_name": "Patched Name", "enabled": False},
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["display_name"] == "Patched Name"
    assert patched["enabled"] is False


def test_admin_can_delete_custom_model(postgres_database_url: str) -> None:
    client = build_client(database_url=postgres_database_url)
    token = issue_token(client, "admin-code")

    client.post(
        "/admin/models",
        headers={"Authorization": f"Bearer {token}"},
        json={**_SAMPLE_MODEL, "id": "custom/to-delete"},
    )

    delete_response = client.delete(
        "/admin/models/custom/to-delete",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"


def test_admin_patch_nonexistent_model_returns_404(postgres_database_url: str) -> None:
    client = build_client(database_url=postgres_database_url)
    token = issue_token(client, "admin-code")

    response = client.patch(
        "/admin/models/custom/does-not-exist",
        headers={"Authorization": f"Bearer {token}"},
        json={"display_name": "Nope"},
    )

    assert response.status_code == 404


def test_admin_delete_nonexistent_model_returns_404(postgres_database_url: str) -> None:
    client = build_client(database_url=postgres_database_url)
    token = issue_token(client, "admin-code")

    response = client.delete(
        "/admin/models/custom/does-not-exist",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
