from datetime import UTC, datetime

from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
from enterprise_llm_proxy.services.identity import OidcIdentity
from enterprise_llm_proxy.services.upstream_oauth import OAuthFlowStart, UpstreamOAuthIdentity


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


class FakeCodexOAuthBroker:
    def __init__(self) -> None:
        self.started_for: list[str] = []
        self.finished: list[tuple[str, str, str]] = []

    def start(self, principal) -> OAuthFlowStart:  # type: ignore[no-untyped-def]
        self.started_for.append(principal.user_id)
        return OAuthFlowStart(
            authorize_url="https://auth.openai.com/oauth/authorize?state=state_123",
            state="state_123",
        )

    def finish(self, *, code: str, state: str, principal) -> UpstreamOAuthIdentity:  # type: ignore[no-untyped-def]
        self.finished.append((code, state, principal.user_id))
        return UpstreamOAuthIdentity(
            subject="openai-user-1",
            email="member@openai.example",
            name="Member OpenAI",
            access_token="oauth-access",
            refresh_token="oauth-refresh",
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
            scopes=["openid", "profile", "email", "offline_access"],
        )

    def refresh(self, refresh_token: str | None) -> dict[str, object]:
        assert refresh_token == "oauth-refresh"
        return {
            "access_token": "oauth-access-refreshed",
            "expires_at": datetime(2031, 1, 1, tzinfo=UTC),
            "state": "active",
        }


def issue_token(client: TestClient, code: str) -> str:
    return client.post("/auth/oidc/callback", json={"code": code}).json()["access_token"]


def test_member_can_bind_private_codex_oauth_and_share_it() -> None:
    broker = FakeCodexOAuthBroker()
    client = TestClient(create_app(oidc_client=FakeOidcClient(), codex_oauth_broker=broker))
    member_token = issue_token(client, "member-code")

    start = client.post(
        "/me/upstream-credentials/codex-oauth/start",
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert start.status_code == 200
    assert start.json()["authorize_url"] == "https://auth.openai.com/oauth/authorize?state=state_123"
    assert broker.started_for == ["u-member"]

    client.get("/auth/oidc/callback?code=member-code", follow_redirects=False)
    callback = client.get(
        "/auth/upstream/codex/callback?code=oauth-code&state=state_123",
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/portal"
    assert broker.finished == [("oauth-code", "state_123", "u-member")]

    listed = client.get(
        "/me/upstream-credentials",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert listed.status_code == 200
    items = listed.json()["data"]
    assert len(items) == 1
    assert items[0]["auth_kind"] == "codex_chatgpt_oauth_managed"
    assert items[0]["provider"] == "openai-codex"
    assert items[0]["visibility"] == "private"
    assert items[0]["owner_principal_id"] == "u-member"
    assert items[0]["max_concurrency"] == 16

    shared = client.post(
        f"/me/upstream-credentials/{items[0]['id']}/share",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert shared.status_code == 200
    assert shared.json()["visibility"] == "enterprise_pool"


def test_admin_can_promote_and_demote_upstream_credentials() -> None:
    broker = FakeCodexOAuthBroker()
    client = TestClient(create_app(oidc_client=FakeOidcClient(), codex_oauth_broker=broker))
    admin_token = issue_token(client, "admin-code")

    created = client.post(
        "/admin/credentials",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "provider": "openai-codex",
            "auth_kind": "codex_chatgpt_oauth_imported",
            "account_id": "imported-openai-user",
            "scopes": ["openid", "offline_access"],
            "access_token": "imported-access",
            "refresh_token": "imported-refresh",
            "max_concurrency": 2,
            "visibility": "private",
            "owner_principal_id": "u-member",
            "source": "codex_chatgpt_oauth_imported",
        },
    )
    credential_id = created.json()["id"]

    promoted = client.post(
        f"/admin/upstream-credentials/{credential_id}/promote",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["visibility"] == "enterprise_pool"

    demoted = client.post(
        f"/admin/upstream-credentials/{credential_id}/demote",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert demoted.status_code == 200
    assert demoted.json()["visibility"] == "private"


def test_member_can_import_codex_cli_credential() -> None:
    client = TestClient(create_app(oidc_client=FakeOidcClient()))
    member_token = issue_token(client, "member-code")

    imported = client.post(
        "/me/upstream-credentials/codex/import",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "account_id": "openai-account-1",
            "access_token": "oauth-access",
            "refresh_token": "oauth-refresh",
            "scopes": ["openid", "profile", "email", "offline_access"],
            "expires_at": "2030-01-01T00:00:00+00:00",
        },
    )

    assert imported.status_code == 201
    payload = imported.json()
    assert payload["auth_kind"] == "codex_chatgpt_oauth_imported"
    assert payload["provider"] == "openai-codex"
    assert payload["visibility"] == "private"
    assert payload["owner_principal_id"] == "u-member"
    assert payload["source"] == "codex_cli_import"
    assert payload["account_id"] == "openai-account-1"
    assert payload["max_concurrency"] == 16

    listed = client.get(
        "/me/upstream-credentials",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == payload["id"]
