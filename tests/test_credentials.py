from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from enterprise_llm_proxy.domain.credentials import CredentialState, ProviderCredential
from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.services.credentials import CredentialPoolService
from enterprise_llm_proxy.services.model_catalog import ModelCatalog
from enterprise_llm_proxy.services.routing import RoutingService


def build_credential(
    credential_id: str,
    *,
    provider: str = "anthropic",
    auth_kind: str = "oauth_subscription",
    state: CredentialState = CredentialState.ACTIVE,
    cooldown_until: datetime | None = None,
    last_selected_at: datetime | None = None,
    concurrent_leases: int = 0,
    max_concurrency: int = 2,
    provider_alias: str | None = None,
    catalog_info: dict | None = None,
) -> ProviderCredential:
    return ProviderCredential(
        id=credential_id,
        provider=provider,
        auth_kind=auth_kind,
        account_id=f"acct-{credential_id}",
        scopes=["model:read"],
        state=state,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        cooldown_until=cooldown_until,
        access_token="access-token",
        refresh_token="refresh-token",
        last_selected_at=last_selected_at,
        concurrent_leases=concurrent_leases,
        max_concurrency=max_concurrency,
        provider_alias=provider_alias,
        catalog_info=catalog_info,
    )


def test_selector_uses_weighted_lru_across_active_credentials() -> None:
    service = CredentialPoolService(
        credentials=[
            build_credential(
                "cred-1",
                last_selected_at=datetime.now(UTC) - timedelta(minutes=1),
            ),
            build_credential(
                "cred-2",
                last_selected_at=datetime.now(UTC) - timedelta(minutes=5),
            ),
        ]
    )

    first = service.select(provider="anthropic", auth_kind="oauth_subscription")
    service.release(first.id)
    second = service.select(provider="anthropic", auth_kind="oauth_subscription")

    assert first.id == "cred-2"
    assert second.id == "cred-1"


def test_selector_skips_cooldown_and_saturated_credentials() -> None:
    service = CredentialPoolService(
        credentials=[
            build_credential(
                "cred-cooldown",
                cooldown_until=datetime.now(UTC) + timedelta(minutes=2),
            ),
            build_credential(
                "cred-busy",
                concurrent_leases=1,
                max_concurrency=1,
            ),
            build_credential("cred-ready"),
        ]
    )

    chosen = service.select(provider="anthropic", auth_kind="oauth_subscription")

    assert chosen.id == "cred-ready"


def test_selector_skips_credentials_without_requested_model() -> None:
    service = CredentialPoolService(
        credentials=[
            build_credential(
                "cred-opus-only",
                provider="claude-max",
                catalog_info={"available_models": ["claude-opus-4-20250514"]},
            ),
            build_credential(
                "cred-sonnet",
                provider="claude-max",
                catalog_info={"available_models": ["claude-sonnet-4-20250514"]},
            ),
        ]
    )

    chosen = service.select(
        provider="claude-max",
        auth_kind="oauth_subscription",
        upstream_model="claude-sonnet-4-20250514",
    )

    assert chosen is not None
    assert chosen.id == "cred-sonnet"


def test_mark_disabled_makes_credential_unselectable() -> None:
    service = CredentialPoolService(
        credentials=[
            build_credential(
                "cred-invalid",
                concurrent_leases=1,
                cooldown_until=datetime.now(UTC) + timedelta(minutes=2),
            ),
            build_credential("cred-ready"),
        ]
    )

    disabled = service.mark_disabled("cred-invalid")
    chosen = service.select(provider="anthropic", auth_kind="oauth_subscription")

    assert disabled is not None
    assert disabled.state == CredentialState.DISABLED
    assert disabled.cooldown_until is None
    assert disabled.concurrent_leases == 0
    assert chosen is not None
    assert chosen.id == "cred-ready"


def test_passthrough_secret_codec_returns_original_value() -> None:
    from enterprise_llm_proxy.security import PassthroughSecretCodec

    codec = PassthroughSecretCodec()

    assert codec.encode("secret-token") == "secret-token"
    assert codec.decode("secret-token") == "secret-token"
    assert codec.encode(None) is None
    assert codec.decode(None) is None


def test_selector_can_prefer_overlay_credentials() -> None:
    service = CredentialPoolService(
        credentials=[
            build_credential(
                "cred-user",
                provider="openai_compat",
                auth_kind="api_key",
            )
        ],
        overlay_credentials=[
            build_credential(
                "cred-system",
                provider="openai_compat",
                auth_kind="api_key",
            )
        ],
    )

    chosen = service.select(
        provider="openai_compat",
        auth_kind="api_key",
        prefer_overlay=True,
    )

    assert chosen.id == "cred-system"


def test_routing_selects_compat_credential_by_provider_alias() -> None:
    principal = Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )
    service = CredentialPoolService(
        credentials=[
            build_credential(
                "cred-zai",
                provider="openai_compat",
                auth_kind="api_key",
                provider_alias="zai-org",
                catalog_info={"available_models": ["glm-4.7-flash"]},
            ),
            build_credential(
                "cred-miro",
                provider="openai_compat",
                auth_kind="api_key",
                provider_alias="mirothinker-1.7",
                catalog_info={"available_models": ["mirothinker-1.7-mini-mlx"]},
            ),
        ]
    )
    routing = RoutingService(ModelCatalog(), service)

    request = routing.build_request(
        protocol="openai_chat",
        payload={
            "model": "mirothinker-1.7/mirothinker-1.7-mini-mlx",
            "messages": [{"role": "user", "content": "hello"}],
        },
        principal=principal,
    )
    credential, _decision = routing.select_credential(request)

    assert request.provider == "openai_compat"
    assert request.provider_alias == "mirothinker-1.7"
    assert credential.id == "cred-miro"


def test_routing_selects_only_credential_that_lists_requested_model() -> None:
    principal = Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )
    service = CredentialPoolService(
        credentials=[
            build_credential(
                "cred-opus-only",
                provider="claude-max",
                catalog_info={"available_models": ["claude-opus-4-20250514"]},
            ),
            build_credential(
                "cred-sonnet",
                provider="claude-max",
                catalog_info={"available_models": ["claude-sonnet-4-20250514"]},
            ),
        ]
    )
    routing = RoutingService(ModelCatalog(), service)

    request = routing.build_request(
        protocol="anthropic_messages",
        payload={
            "model": "claude-max/claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 16,
        },
        principal=principal,
    )
    credential, _decision = routing.select_credential(request)

    assert credential.id == "cred-sonnet"


def test_routing_reports_cooldown_when_all_matching_credentials_are_cooling_down() -> None:
    principal = Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )
    service = CredentialPoolService(
        credentials=[
            build_credential(
                "cred-cooldown",
                provider="claude-max",
                cooldown_until=datetime.now(UTC) + timedelta(minutes=2),
            )
        ]
    )
    routing = RoutingService(ModelCatalog(), service)
    request = routing.build_request(
        protocol="anthropic_messages",
        payload={
            "model": "claude-max/claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 16,
        },
        principal=principal,
    )

    with pytest.raises(HTTPException) as exc_info:
        routing.select_credential(request)

    assert exc_info.value.status_code == 429
    assert "cooldown" in str(exc_info.value.detail)


def test_routing_reports_saturation_when_all_matching_credentials_are_busy() -> None:
    principal = Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )
    service = CredentialPoolService(
        credentials=[
            build_credential(
                "cred-busy",
                provider="openai-codex",
                auth_kind="codex_chatgpt_oauth_imported",
                concurrent_leases=1,
                max_concurrency=1,
            )
        ]
    )
    routing = RoutingService(ModelCatalog(), service)
    request = routing.build_request(
        protocol="openai_chat",
        payload={
            "model": "openai-codex/gpt-5-codex",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 16,
        },
        principal=principal,
    )

    with pytest.raises(HTTPException) as exc_info:
        routing.select_credential(request)

    assert exc_info.value.status_code == 503
    assert "busy" in str(exc_info.value.detail)
    assert "saturated" in str(exc_info.value.detail)
