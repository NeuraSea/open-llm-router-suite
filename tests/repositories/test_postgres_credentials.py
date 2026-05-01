from __future__ import annotations

from datetime import UTC, datetime, timedelta

from enterprise_llm_proxy.domain.credentials import CredentialState, CredentialVisibility
from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.security import PassthroughSecretCodec


def build_principal(*, user_id: str = "u-member", role: str = "member") -> Principal:
    return Principal(
        user_id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
        team_ids=["platform"],
        role=role,
    )


def test_repository_round_trips_provider_credential(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.credentials import PostgresCredentialRepository

    repository = PostgresCredentialRepository(
        session_factory=postgres_session_factory,
        secret_codec=PassthroughSecretCodec(),
    )

    created = repository.create_credential(
        provider="openai",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-openai-1",
        scopes=["openid", "profile"],
        access_token="access-token",
        refresh_token="refresh-token",
        max_concurrency=2,
        owner_principal_id="u-member",
        visibility=CredentialVisibility.PRIVATE,
        source="codex_cli_import",
    )

    fetched = repository.get_credential(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.account_id == "acct-openai-1"
    assert fetched.access_token == "access-token"
    assert fetched.refresh_token == "refresh-token"
    assert fetched.visibility == CredentialVisibility.PRIVATE


def test_repository_selects_weighted_lru_candidate(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.credentials import PostgresCredentialRepository

    repository = PostgresCredentialRepository(
        session_factory=postgres_session_factory,
        secret_codec=PassthroughSecretCodec(),
    )
    older = repository.create_credential(
        provider="anthropic",
        auth_kind="oauth_subscription",
        account_id="acct-older",
        scopes=["model:read"],
        access_token="older",
        refresh_token="older-refresh",
        max_concurrency=2,
    )
    newer = repository.create_credential(
        provider="anthropic",
        auth_kind="oauth_subscription",
        account_id="acct-newer",
        scopes=["model:read"],
        access_token="newer",
        refresh_token="newer-refresh",
        max_concurrency=2,
    )
    repository.update_credential(
        older.replace(last_selected_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    repository.update_credential(
        newer.replace(last_selected_at=datetime.now(UTC) - timedelta(minutes=1))
    )

    chosen = repository.select(
        provider="anthropic",
        auth_kind="oauth_subscription",
        principal=None,
    )

    assert chosen is not None
    assert chosen.id == older.id
    assert chosen.concurrent_leases == 1


def test_repository_skips_cooldown_and_saturated_candidates(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.credentials import PostgresCredentialRepository

    repository = PostgresCredentialRepository(
        session_factory=postgres_session_factory,
        secret_codec=PassthroughSecretCodec(),
    )
    repository.create_credential(
        provider="anthropic",
        auth_kind="oauth_subscription",
        account_id="acct-cooldown",
        scopes=["model:read"],
        access_token="cooldown",
        refresh_token="cooldown-refresh",
        max_concurrency=2,
    )
    cooldown_credential = repository.list_credentials()[0]
    repository.update_credential(
        cooldown_credential.replace(
            state=CredentialState.ACTIVE,
            cooldown_until=datetime.now(UTC) + timedelta(minutes=2),
        )
    )
    saturated = repository.create_credential(
        provider="anthropic",
        auth_kind="oauth_subscription",
        account_id="acct-saturated",
        scopes=["model:read"],
        access_token="busy",
        refresh_token="busy-refresh",
        max_concurrency=1,
    )
    repository.update_credential(saturated.replace(concurrent_leases=1))
    ready = repository.create_credential(
        provider="anthropic",
        auth_kind="oauth_subscription",
        account_id="acct-ready",
        scopes=["model:read"],
        access_token="ready",
        refresh_token="ready-refresh",
        max_concurrency=2,
    )

    chosen = repository.select(
        provider="anthropic",
        auth_kind="oauth_subscription",
        principal=None,
    )

    assert chosen is not None
    assert chosen.id == ready.id


def test_repository_reactivates_expired_cooldown_candidate(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.credentials import PostgresCredentialRepository

    repository = PostgresCredentialRepository(
        session_factory=postgres_session_factory,
        secret_codec=PassthroughSecretCodec(),
    )
    created = repository.create_credential(
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct-cooldown-expired",
        scopes=["model:read"],
        access_token="cooldown",
        refresh_token="cooldown-refresh",
        max_concurrency=2,
    )
    repository.update_credential(
        created.replace(
            state=CredentialState.COOLDOWN,
            cooldown_until=datetime.now(UTC) - timedelta(minutes=1),
        )
    )

    chosen = repository.select(
        provider="claude-max",
        auth_kind="oauth_subscription",
        principal=None,
    )

    assert chosen is not None
    assert chosen.id == created.id
    assert chosen.state == CredentialState.ACTIVE
    assert chosen.cooldown_until is None


def test_repository_select_skips_credentials_without_requested_model(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.credentials import PostgresCredentialRepository

    repository = PostgresCredentialRepository(
        session_factory=postgres_session_factory,
        secret_codec=PassthroughSecretCodec(),
    )
    repository.create_credential(
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct-opus-only",
        scopes=["model:read"],
        access_token="opus-token",
        refresh_token="opus-refresh",
        max_concurrency=2,
        catalog_info={"available_models": ["claude-opus-4-20250514"]},
    )
    sonnet = repository.create_credential(
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct-sonnet",
        scopes=["model:read"],
        access_token="sonnet-token",
        refresh_token="sonnet-refresh",
        max_concurrency=2,
        catalog_info={"available_models": ["claude-sonnet-4-20250514"]},
    )

    chosen = repository.select(
        provider="claude-max",
        auth_kind="oauth_subscription",
        upstream_model="claude-sonnet-4-20250514",
        principal=None,
    )

    assert chosen is not None
    assert chosen.id == sonnet.id


def test_repository_mark_disabled_makes_credential_unavailable(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.credentials import PostgresCredentialRepository

    repository = PostgresCredentialRepository(
        session_factory=postgres_session_factory,
        secret_codec=PassthroughSecretCodec(),
    )
    created = repository.create_credential(
        provider="claude-max",
        auth_kind="oauth_subscription",
        account_id="acct-disabled",
        scopes=["model:read"],
        access_token="stale-token",
        refresh_token="refresh-token",
        max_concurrency=1,
    )
    repository.update_credential(
        created.replace(
            concurrent_leases=1,
            cooldown_until=datetime.now(UTC) + timedelta(minutes=3),
        )
    )

    disabled = repository.mark_disabled(created.id)
    chosen = repository.select(
        provider="claude-max",
        auth_kind="oauth_subscription",
        principal=None,
    )

    assert disabled is not None
    assert disabled.state == CredentialState.DISABLED
    assert disabled.cooldown_until is None
    assert disabled.concurrent_leases == 0
    assert chosen is None


def test_repository_release_clamps_concurrent_leases_at_zero(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.credentials import PostgresCredentialRepository

    repository = PostgresCredentialRepository(
        session_factory=postgres_session_factory,
        secret_codec=PassthroughSecretCodec(),
    )
    created = repository.create_credential(
        provider="openai",
        auth_kind="api_key",
        account_id="acct-openai-1",
        scopes=["model:read"],
        access_token="access-token",
        refresh_token=None,
        max_concurrency=1,
    )

    repository.release(created.id)
    repository.release(created.id)
    fetched = repository.get_credential(created.id)

    assert fetched is not None
    assert fetched.concurrent_leases == 0


def test_repository_resets_only_stale_leases(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.credentials import PostgresCredentialRepository

    clock_value = datetime(2026, 4, 16, 12, 0, tzinfo=UTC)

    def clock() -> datetime:
        return clock_value

    repository = PostgresCredentialRepository(
        session_factory=postgres_session_factory,
        secret_codec=PassthroughSecretCodec(),
        clock=clock,
    )
    stale = repository.create_credential(
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-stale",
        scopes=["model:read"],
        access_token="access-token",
        refresh_token="refresh-token",
        max_concurrency=1,
    )
    fresh = repository.create_credential(
        provider="openai-codex",
        auth_kind="codex_chatgpt_oauth_imported",
        account_id="acct-fresh",
        scopes=["model:read"],
        access_token="access-token",
        refresh_token="refresh-token",
        max_concurrency=1,
    )
    repository.update_credential(stale.replace(concurrent_leases=1))
    clock_value = clock_value + timedelta(minutes=10)
    repository.update_credential(fresh.replace(concurrent_leases=1))
    clock_value = clock_value + timedelta(minutes=2)

    reset_count = repository.reset_stale_leases(max_age_seconds=300)

    assert reset_count == 1
    assert repository.get_credential(stale.id).concurrent_leases == 0  # type: ignore[union-attr]
    assert repository.get_credential(fresh.id).concurrent_leases == 1  # type: ignore[union-attr]
