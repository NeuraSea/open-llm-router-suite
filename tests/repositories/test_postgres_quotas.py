from __future__ import annotations


def test_quota_repository_sets_and_lists_rules(postgres_session_factory) -> None:
    from enterprise_llm_proxy.repositories.quotas import PostgresQuotaRepository

    repository = PostgresQuotaRepository(session_factory=postgres_session_factory)

    repository.set_quota(scope_type="team", scope_id="platform", limit=250000)
    repository.set_quota(scope_type="user", scope_id="u-member", limit=1000)

    rules = repository.list_quotas()

    assert [(rule.scope_type, rule.scope_id, rule.limit) for rule in rules] == [
        ("team", "platform", 250000),
        ("user", "u-member", 1000),
    ]
