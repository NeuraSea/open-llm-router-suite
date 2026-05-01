from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.domain.inference import UsageEvent
from enterprise_llm_proxy.services.identity import OidcIdentity
from enterprise_llm_proxy.services.usage import UsageLedger


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


def build_client(usage_ledger: UsageLedger | None = None) -> TestClient:
    return TestClient(
        create_app(
            settings=AppSettings(
                router_public_base_url="https://router.example.com/v1",
                feishu_client_id="cli_test_123",
                feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
                session_cookie_secure=False,
            ),
            oidc_client=FakeOidcClient(),
            usage_ledger=usage_ledger,
        )
    )


def issue_human_token(client: TestClient, code: str) -> str:
    return client.post("/auth/oidc/callback", json={"code": code}).json()["access_token"]


def make_event(
    *,
    request_id: str,
    principal_id: str,
    principal_email: str,
    model_profile: str,
    tokens_in: int,
    tokens_out: int,
    created_at: float | None = None,
    status: str = "success",
) -> UsageEvent:
    now = datetime.now(UTC).timestamp()
    return UsageEvent(
        request_id=request_id,
        principal_id=principal_id,
        principal_email=principal_email,
        model_profile=model_profile,
        provider="anthropic",
        credential_id="cred-1",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=100,
        status=status,
        created_at=created_at if created_at is not None else now,
    )


# ---- Tests ----


def test_usage_summary_groups_by_user_and_model() -> None:
    ledger = UsageLedger()
    # User A on model X: 2 events
    ledger.record(
        make_event(
            request_id="r1",
            principal_id="u-a",
            principal_email="a@example.com",
            model_profile="claude-sonnet",
            tokens_in=100,
            tokens_out=50,
        ),
        team_ids=[],
    )
    ledger.record(
        make_event(
            request_id="r2",
            principal_id="u-a",
            principal_email="a@example.com",
            model_profile="claude-sonnet",
            tokens_in=200,
            tokens_out=80,
        ),
        team_ids=[],
    )
    # User B on model Y: 1 event
    ledger.record(
        make_event(
            request_id="r3",
            principal_id="u-b",
            principal_email="b@example.com",
            model_profile="gpt-4o",
            tokens_in=150,
            tokens_out=60,
        ),
        team_ids=[],
    )

    client = build_client(usage_ledger=ledger)
    admin_token = issue_human_token(client, "admin-code")
    resp = client.get(
        "/admin/usage/summary",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 2

    # Build lookup by (principal_id, model_profile)
    lookup = {(row["principal_id"], row["model_profile"]): row for row in data}

    row_a = lookup[("u-a", "claude-sonnet")]
    assert row_a["tokens_in"] == 300
    assert row_a["tokens_out"] == 130
    assert row_a["request_count"] == 2
    assert row_a["principal_email"] == "a@example.com"

    row_b = lookup[("u-b", "gpt-4o")]
    assert row_b["tokens_in"] == 150
    assert row_b["tokens_out"] == 60
    assert row_b["request_count"] == 1
    assert row_b["principal_email"] == "b@example.com"


def test_usage_summary_filters_by_period() -> None:
    ledger = UsageLedger()
    # Old event (>30d ago)
    old_ts = (datetime.now(UTC) - timedelta(days=31)).timestamp()
    ledger.record(
        make_event(
            request_id="old-1",
            principal_id="u-a",
            principal_email="a@example.com",
            model_profile="claude-sonnet",
            tokens_in=999,
            tokens_out=999,
            created_at=old_ts,
        ),
        team_ids=[],
    )
    # Recent event
    ledger.record(
        make_event(
            request_id="recent-1",
            principal_id="u-a",
            principal_email="a@example.com",
            model_profile="claude-sonnet",
            tokens_in=10,
            tokens_out=5,
        ),
        team_ids=[],
    )

    client = build_client(usage_ledger=ledger)
    admin_token = issue_human_token(client, "admin-code")
    resp = client.get(
        "/admin/usage/summary?period=30d",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["tokens_in"] == 10
    assert data[0]["request_count"] == 1


def test_usage_summary_all_period() -> None:
    ledger = UsageLedger()
    old_ts = (datetime.now(UTC) - timedelta(days=60)).timestamp()
    ledger.record(
        make_event(
            request_id="old-1",
            principal_id="u-a",
            principal_email="a@example.com",
            model_profile="claude-sonnet",
            tokens_in=100,
            tokens_out=50,
            created_at=old_ts,
        ),
        team_ids=[],
    )

    client = build_client(usage_ledger=ledger)
    admin_token = issue_human_token(client, "admin-code")
    resp = client.get(
        "/admin/usage/summary?period=all",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["tokens_in"] == 100


def test_non_admin_cannot_get_summary() -> None:
    client = build_client()
    member_token = issue_human_token(client, "member-code")
    resp = client.get(
        "/admin/usage/summary",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403
