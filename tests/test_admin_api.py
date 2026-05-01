from datetime import UTC, datetime

from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
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


class FakeCredentialRefresher:
    def refresh(self, provider: str, refresh_token: str | None) -> dict[str, object]:
        assert provider == "anthropic"
        assert refresh_token == "refresh-1"
        return {
            "access_token": "refreshed-access",
            "expires_at": datetime(2030, 1, 1, tzinfo=UTC),
            "state": "active",
        }


def issue_token(client: TestClient, code: str) -> str:
    response = client.post("/auth/oidc/callback", json={"code": code})
    return response.json()["access_token"]


def test_admin_can_create_and_list_credentials() -> None:
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            credential_refresher=FakeCredentialRefresher(),
        )
    )
    admin_token = issue_token(client, "admin-code")

    create = client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "provider": "anthropic",
            "auth_kind": "oauth_subscription",
            "account_id": "acct-1",
            "scopes": ["model:read"],
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "max_concurrency": 3,
        },
    )

    assert create.status_code == 201
    payload = create.json()
    assert payload["provider"] == "anthropic"
    assert payload["state"] == "active"

    listed = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert listed.status_code == 200
    items = listed.json()["data"]
    assert len(items) == 1
    assert items[0]["account_id"] == "acct-1"


def test_non_admin_cannot_manage_credentials() -> None:
    client = TestClient(create_app(oidc_client=FakeOidcClient()))
    member_token = issue_token(client, "member-code")

    response = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert response.status_code == 403


def test_refresh_endpoint_updates_credential_state() -> None:
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            credential_refresher=FakeCredentialRefresher(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    created = client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "provider": "anthropic",
            "auth_kind": "oauth_subscription",
            "account_id": "acct-1",
            "scopes": ["model:read"],
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "max_concurrency": 3,
        },
    )
    credential_id = created.json()["id"]

    refreshed = client.post(
        f"/admin/credentials/{credential_id}/refresh",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["state"] == "active"
    assert payload["expires_at"].startswith("2030-01-01T00:00:00")


def test_admin_can_update_credential_max_concurrency() -> None:
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            credential_refresher=FakeCredentialRefresher(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    created = client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "provider": "anthropic",
            "auth_kind": "oauth_subscription",
            "account_id": "acct-1",
            "scopes": ["model:read"],
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "max_concurrency": 3,
        },
    )
    credential_id = created.json()["id"]

    updated = client.patch(
        f"/admin/credentials/{credential_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"max_concurrency": 8},
    )

    assert updated.status_code == 200
    assert updated.json()["max_concurrency"] == 8

    listed = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert listed.json()["data"][0]["max_concurrency"] == 8


def test_admin_rejects_invalid_credential_max_concurrency() -> None:
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            credential_refresher=FakeCredentialRefresher(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    created = client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "provider": "anthropic",
            "auth_kind": "oauth_subscription",
            "account_id": "acct-1",
            "scopes": ["model:read"],
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "max_concurrency": 3,
        },
    )
    credential_id = created.json()["id"]

    updated = client.patch(
        f"/admin/credentials/{credential_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"max_concurrency": 0},
    )

    assert updated.status_code == 422


def test_admin_can_delete_credentials() -> None:
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            credential_refresher=FakeCredentialRefresher(),
        )
    )
    admin_token = issue_token(client, "admin-code")
    created = client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "provider": "anthropic",
            "auth_kind": "oauth_subscription",
            "account_id": "acct-1",
            "scopes": ["model:read"],
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "max_concurrency": 3,
        },
    )
    credential_id = created.json()["id"]

    deleted = client.delete(
        f"/admin/credentials/{credential_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert deleted.status_code == 204

    listed = client.get(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert listed.json()["data"] == []
