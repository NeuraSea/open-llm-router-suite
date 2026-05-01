from __future__ import annotations

from enterprise_llm_proxy.domain.inference import UsageEvent


def build_event(
    request_id: str,
    *,
    principal_id: str = "u-member",
    status: str = "success",
    tokens_in: int = 10,
    tokens_out: int = 15,
) -> UsageEvent:
    return UsageEvent(
        request_id=request_id,
        principal_id=principal_id,
        model_profile="openai/gpt-4.1",
        provider="openai",
        credential_id="cred-openai-1",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=900,
        status=status,
        created_at=1_710_806_400.0,
    )


def test_usage_repository_records_event_and_team_memberships(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.usage import PostgresUsageRepository

    repository = PostgresUsageRepository(session_factory=postgres_session_factory)
    event = build_event("req-1")

    repository.record(event, team_ids=["platform", "sre"])
    events = repository.list_events()

    assert len(events) == 1
    assert events[0].request_id == "req-1"
    assert repository.total_for_team("platform") == 25
    assert repository.total_for_team("sre") == 25


def test_usage_repository_totals_successful_tokens_for_user(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.usage import PostgresUsageRepository

    repository = PostgresUsageRepository(session_factory=postgres_session_factory)

    repository.record(build_event("req-success", tokens_in=40, tokens_out=60), team_ids=["platform"])
    repository.record(
        build_event("req-failed", status="failed", tokens_in=100, tokens_out=200),
        team_ids=["platform"],
    )

    assert repository.total_for_user("u-member") == 100


def test_usage_repository_totals_successful_tokens_for_team(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.usage import PostgresUsageRepository

    repository = PostgresUsageRepository(session_factory=postgres_session_factory)

    repository.record(build_event("req-1", tokens_in=15, tokens_out=20), team_ids=["platform"])
    repository.record(build_event("req-2", tokens_in=5, tokens_out=10), team_ids=["sre"])
    repository.record(
        build_event("req-3", status="failed", tokens_in=300, tokens_out=400),
        team_ids=["platform"],
    )

    assert repository.total_for_team("platform") == 35
