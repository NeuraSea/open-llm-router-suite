from __future__ import annotations

from enterprise_llm_proxy.domain.credentials import (
    CredentialState,
    CredentialVisibility,
    ProviderCredential,
)
from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.services.credentials import CredentialPoolService
from enterprise_llm_proxy.services.model_catalog import ModelCatalog


def _make_subscription_credential(
    *,
    provider: str,
    auth_kind: str,
    owner_principal_id: str,
    available_models: list[str],
) -> ProviderCredential:
    return ProviderCredential(
        id=f"cred-{provider}",
        provider=provider,
        auth_kind=auth_kind,
        account_id=f"{provider}-acct",
        scopes=["openid", "profile"],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token="token",
        refresh_token="refresh",
        owner_principal_id=owner_principal_id,
        visibility=CredentialVisibility.PRIVATE,
        source="bind-import",
        max_concurrency=1,
        billing_model="subscription",
        catalog_info={"available_models": available_models},
    )


def _make_compat_credential(
    *,
    credential_id: str,
    provider: str,
    provider_alias: str | None,
    owner_principal_id: str,
    available_models: list[str] | None,
) -> ProviderCredential:
    return ProviderCredential(
        id=credential_id,
        provider=provider,
        auth_kind="api_key",
        account_id=f"{provider}-acct",
        scopes=["model:read"],
        state=CredentialState.ACTIVE,
        expires_at=None,
        cooldown_until=None,
        access_token="token",
        refresh_token=None,
        owner_principal_id=owner_principal_id,
        visibility=CredentialVisibility.PRIVATE,
        source="byok_compat",
        max_concurrency=1,
        provider_alias=provider_alias,
        catalog_info=(
            {"available_models": available_models}
            if available_models is not None
            else None
        ),
    )


def test_bound_subscription_credentials_override_static_provider_catalogs() -> None:
    principal = Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )
    credential_pool = CredentialPoolService(
        credentials=[
            _make_subscription_credential(
                provider="openai-codex",
                auth_kind="codex_chatgpt_oauth_imported",
                owner_principal_id=principal.user_id,
                available_models=["gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"],
            ),
            _make_subscription_credential(
                provider="claude-max",
                auth_kind="oauth_subscription",
                owner_principal_id=principal.user_id,
                available_models=["claude-sonnet-4-6", "claude-opus-4-6"],
            ),
        ]
    )

    models = ModelCatalog().list_models_for_principal(principal, credential_pool)
    ids = {item["id"] for item in models}

    assert "openai-codex/gpt-5.4" in ids
    assert "openai-codex/gpt-5.4-mini" in ids
    assert "openai-codex/gpt-5.3-codex" in ids
    assert "openai-codex/gpt-5-codex" not in ids
    assert "claude-max/claude-sonnet-4-6" in ids
    assert "claude-max/claude-opus-4-6" in ids
    assert "claude-max/claude-sonnet-4-20250514" not in ids


def test_compat_alias_models_are_exposed_and_resolved_per_alias() -> None:
    principal = Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )
    credential_pool = CredentialPoolService(
        credentials=[
            _make_compat_credential(
                credential_id="cred-zai",
                provider="openai_compat",
                provider_alias="zai-org",
                owner_principal_id=principal.user_id,
                available_models=["glm-4.7-flash"],
            ),
            _make_compat_credential(
                credential_id="cred-miro",
                provider="openai_compat",
                provider_alias="mirothinker-1.7",
                owner_principal_id=principal.user_id,
                available_models=["mirothinker-1.7-mini-mlx"],
            ),
        ]
    )
    catalog = ModelCatalog()

    models = catalog.list_models_for_principal(principal, credential_pool, routable_only=True)
    by_id = {item["id"]: item for item in models}

    assert "zai-org/glm-4.7-flash" in by_id
    assert "mirothinker-1.7/mirothinker-1.7-mini-mlx" in by_id
    resolved = catalog.resolve_model_for_principal(
        "mirothinker-1.7/mirothinker-1.7-mini-mlx",
        principal,
        credential_pool,
    )
    assert resolved["provider"] == "openai_compat"
    assert resolved["upstream_model"] == "mirothinker-1.7-mini-mlx"
    assert resolved["model_profile"] == "mirothinker-1.7-mini-mlx"
    assert resolved["provider_alias"] == "mirothinker-1.7"


def test_routable_only_filters_out_unconfigured_static_provider_groups() -> None:
    principal = Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )
    credential_pool = CredentialPoolService(
        credentials=[
            _make_subscription_credential(
                provider="openai-codex",
                auth_kind="codex_chatgpt_oauth_imported",
                owner_principal_id=principal.user_id,
                available_models=["gpt-5.4"],
            )
        ]
    )

    models = ModelCatalog().list_models_for_principal(principal, credential_pool, routable_only=True)
    ids = {item["id"] for item in models}
    providers = {item["provider"] for item in models}

    assert "openai-codex/gpt-5.4" in ids
    assert "openai/gpt-4.1" not in ids
    assert "openai" not in providers


def test_jina_catalog_models_expose_embedding_and_rerank_protocols() -> None:
    principal = Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )
    credential_pool = CredentialPoolService(
        credentials=[
            _make_subscription_credential(
                provider="jina",
                auth_kind="api_key",
                owner_principal_id=principal.user_id,
                available_models=["jina-embeddings-v4", "jina-reranker-v3"],
            )
        ]
    )

    models = ModelCatalog().list_models_for_principal(principal, credential_pool, routable_only=True)
    by_id = {item["id"]: item for item in models}

    assert by_id["jina/jina-embeddings-v4"]["supported_protocols"] == [
        "openai_embeddings",
        "jina_rerank",
    ]
    assert by_id["jina/jina-reranker-v3"]["provider"] == "jina"


def test_stale_compat_credentials_without_alias_or_catalog_are_hidden_from_routable_models() -> None:
    principal = Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )
    credential_pool = CredentialPoolService(
        credentials=[
            _make_compat_credential(
                credential_id="cred-stale",
                provider="openai_compat",
                provider_alias=None,
                owner_principal_id=principal.user_id,
                available_models=None,
            )
        ]
    )

    models = ModelCatalog().list_models_for_principal(principal, credential_pool, routable_only=True)

    assert models == []
