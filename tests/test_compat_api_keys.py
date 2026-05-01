from __future__ import annotations

from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
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


def issue_token(client: TestClient) -> str:
    return client.post("/auth/oidc/callback", json={"code": "member-code"}).json()["access_token"]


def test_compat_api_key_requires_provider_alias(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "enterprise_llm_proxy.app.discover_compat_models",
        lambda **kwargs: ["glm-4.7-flash"],
    )
    client = TestClient(create_app(oidc_client=FakeOidcClient()))
    token = issue_token(client)

    response = client.post(
        "/me/upstream-credentials/api-key",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "openai_compat",
            "api_key": "sk-compat",
            "label": "LM Studio",
            "base_url": "http://lmstudio.local:1234/v1",
        },
    )

    assert response.status_code == 422
    assert "provider_alias is required" in response.json()["detail"]


def test_compat_api_key_persists_alias_and_discovered_catalog(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "enterprise_llm_proxy.app.discover_compat_models",
        lambda **kwargs: ["glm-4.7-flash", "gpt-oss-120b"],
    )
    client = TestClient(create_app(oidc_client=FakeOidcClient()))
    token = issue_token(client)

    response = client.post(
        "/me/upstream-credentials/api-key",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "openai_compat",
            "provider_alias": "zai-org",
            "api_key": "sk-compat",
            "label": "ZAI Compat",
            "base_url": "http://lmstudio.local:1234/v1",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["provider"] == "openai_compat"
    assert payload["provider_alias"] == "zai-org"
    assert payload["catalog_info"] == {"available_models": ["glm-4.7-flash", "gpt-oss-120b"]}


def test_jina_api_key_is_supported_with_default_catalog() -> None:
    client = TestClient(create_app(oidc_client=FakeOidcClient()))
    token = issue_token(client)

    response = client.post(
        "/me/upstream-credentials/api-key",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": "jina",
            "api_key": "jina-test-key",
            "label": "Jina",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["provider"] == "jina"
    assert payload["account_id"] == "Jina"
    assert "jina-embeddings-v4" in payload["catalog_info"]["available_models"]
    assert "jina-reranker-v3" in payload["catalog_info"]["available_models"]
