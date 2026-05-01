from __future__ import annotations

from datetime import UTC, datetime

from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.services.api_keys import PlatformApiKey


def build_principal() -> Principal:
    return Principal(
        user_id="u-member",
        email="member@example.com",
        name="Member",
        team_ids=["platform"],
        role="member",
    )


def test_api_key_repository_round_trips_principal_snapshot(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.api_keys import PostgresPlatformApiKeyRepository

    repository = PostgresPlatformApiKeyRepository(session_factory=postgres_session_factory)
    record = PlatformApiKey(
        id="key_1",
        principal=build_principal(),
        name="MacBook Pro",
        key_prefix="elp_test_key",
        key_hash="hash-1",
        created_at=datetime.now(UTC),
    )

    repository.save(record)
    fetched = repository.find_by_hash("hash-1")

    assert fetched is not None
    assert fetched.id == "key_1"
    assert fetched.principal.user_id == "u-member"
    assert fetched.principal.email == "member@example.com"
    assert fetched.principal.team_ids == ["platform"]


def test_api_key_repository_finds_record_by_hash(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.api_keys import PostgresPlatformApiKeyRepository

    repository = PostgresPlatformApiKeyRepository(session_factory=postgres_session_factory)
    repository.save(
        PlatformApiKey(
            id="key_1",
            principal=build_principal(),
            name="MacBook Pro",
            key_prefix="elp_test_key",
            key_hash="hash-1",
            created_at=datetime.now(UTC),
        )
    )

    assert repository.find_by_hash("missing-hash") is None
    assert repository.find_by_hash("hash-1") is not None
