from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.domain.credentials import (
    CredentialState,
    CredentialVisibility,
    ProviderCredential,
)
from enterprise_llm_proxy.services.identity import OidcIdentity
from enterprise_llm_proxy.services.model_catalog import ModelDefinition


def test_healthz_reports_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_models_requires_authentication() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/models")

    assert response.status_code == 401


def test_app_bootstrap_ignores_invalid_proxy_env_when_feishu_client_is_configured(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:8118source")
    settings = AppSettings(
        feishu_client_id="cli_test",
        feishu_client_secret="secret_test",
        feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
        feishu_token_url="https://open.feishu.cn/open-apis/authen/v2/oauth/token",
        feishu_userinfo_url="https://open.feishu.cn/open-apis/authen/v1/user_info",
    )

    client = TestClient(create_app(settings=settings))

    response = client.get("/healthz")

    assert response.status_code == 200


class FakeOidcClient:
    def exchange_code(self, code: str) -> dict[str, str]:
        return {"access_token": f"provider-token-{code}"}

    def fetch_userinfo(self, access_token: str) -> OidcIdentity:
        if access_token.endswith("admin-code"):
            return OidcIdentity(
                subject="u-admin",
                email="admin@example.com",
                name="Admin",
                team_ids=["platform"],
                role="admin",
            )

        return OidcIdentity(
            subject="u-alice",
            email="alice@example.com",
            name="Alice",
            team_ids=["platform"],
            role="member",
        )


class FakeLMStudioService:
    def __init__(self, model_ids: list[str]) -> None:
        self._model_ids = model_ids

    def build_system_credential(self) -> ProviderCredential:
        return ProviderCredential(
            id="cred-system-lmstudio",
            provider="openai_compat",
            auth_kind="api_key",
            account_id="lm-studio",
            scopes=["chat", "responses", "embeddings"],
            state=CredentialState.ACTIVE,
            expires_at=None,
            cooldown_until=None,
            access_token='{"api_key":"lm-token","base_url":"http://host.docker.internal:1234/v1"}',
            refresh_token=None,
            visibility=CredentialVisibility.ENTERPRISE_POOL,
            source="system_lm_studio",
            max_concurrency=1,
            provider_alias="lmstudio",
            catalog_info={"available_models": list(self._model_ids)},
        )

    def list_models(self) -> list[ModelDefinition]:
        return [
            ModelDefinition(
                id=f"lmstudio/{model_id}",
                object="model",
                owned_by="openai_compat",
                provider="openai_compat",
                model_profile=model_id,
                upstream_model=model_id,
                display_name=model_id,
                supported_protocols=["openai_chat", "openai_responses", "openai_embeddings"],
                supported_clients=["codex"],
                auth_modes=["api_key"],
                description=f"{model_id} via LM Studio",
            )
            for model_id in self._model_ids
        ]

    def has_model(self, model_id: str) -> bool:
        return model_id in self._model_ids


def test_oidc_callback_issues_gateway_token() -> None:
    client = TestClient(create_app(oidc_client=FakeOidcClient()))

    response = client.post("/auth/oidc/callback", json={"code": "alice-code"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["principal"]["email"] == "alice@example.com"
    assert payload["access_token"]


def test_models_returns_only_routable_models_for_authenticated_user() -> None:
    client = TestClient(create_app(oidc_client=FakeOidcClient()))
    auth = client.post("/auth/oidc/callback", json={"code": "alice-code"})
    token = auth.json()["access_token"]

    response = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == []


def test_models_include_lm_studio_models_when_configured() -> None:
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            lmstudio_service=FakeLMStudioService(["zai-org/glm-4.7-flash"]),
        )
    )
    auth = client.post("/auth/oidc/callback", json={"code": "alice-code"})
    token = auth.json()["access_token"]

    response = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["data"]}
    assert "lmstudio/zai-org/glm-4.7-flash" in ids


def test_ui_models_routable_only_hides_unconfigured_openai_group() -> None:
    client = TestClient(
        create_app(
            oidc_client=FakeOidcClient(),
            lmstudio_service=FakeLMStudioService(["zai-org/glm-4.7-flash"]),
        )
    )
    auth = client.post("/auth/oidc/callback", json={"code": "alice-code"})
    token = auth.json()["access_token"]

    response = client.get(
        "/ui/models?routable_only=true",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["data"]}
    providers = {item["provider"] for item in response.json()["data"]}
    assert "lmstudio/zai-org/glm-4.7-flash" in ids
    assert "openai/gpt-4.1" not in ids
    assert "openai" not in providers
