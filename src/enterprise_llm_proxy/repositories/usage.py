from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from enterprise_llm_proxy.domain.inference import UsageEvent
from enterprise_llm_proxy.repositories.models import UsageEventRecord, UsageEventTeamRecord


class PostgresUsageRepository:
    def __init__(self, *, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(self, event: UsageEvent, *, team_ids: list[str]) -> None:
        created_at = datetime.fromtimestamp(event.created_at, tz=UTC)
        with self._session_factory() as session:
            session.add(
                UsageEventRecord(
                    request_id=event.request_id,
                    principal_id=event.principal_id,
                    principal_email=event.principal_email,
                    model_profile=event.model_profile,
                    provider=event.provider,
                    credential_id=event.credential_id,
                    tokens_in=event.tokens_in,
                    tokens_out=event.tokens_out,
                    latency_ms=event.latency_ms,
                    status=event.status,
                    created_at=created_at,
                )
            )
            for team_id in team_ids:
                session.add(UsageEventTeamRecord(request_id=event.request_id, team_id=team_id))
            session.commit()

    def list_events(self) -> list[UsageEvent]:
        with self._session_factory() as session:
            records = session.scalars(
                select(UsageEventRecord).order_by(UsageEventRecord.created_at.desc())
            ).all()
        return [
            UsageEvent(
                request_id=item.request_id,
                principal_id=item.principal_id,
                principal_email=item.principal_email,
                model_profile=item.model_profile,
                provider=item.provider,
                credential_id=item.credential_id,
                tokens_in=item.tokens_in,
                tokens_out=item.tokens_out,
                latency_ms=item.latency_ms,
                status=item.status,
                created_at=item.created_at.timestamp(),
            )
            for item in records
        ]

    def summarize_usage(self, since: datetime | None) -> list[dict]:
        with self._session_factory() as session:
            q = (
                select(
                    UsageEventRecord.principal_id,
                    UsageEventRecord.principal_email,
                    UsageEventRecord.model_profile,
                    func.sum(UsageEventRecord.tokens_in).label("tokens_in"),
                    func.sum(UsageEventRecord.tokens_out).label("tokens_out"),
                    func.count(UsageEventRecord.request_id).label("request_count"),
                )
                .where(UsageEventRecord.status == "success")
                .group_by(
                    UsageEventRecord.principal_id,
                    UsageEventRecord.principal_email,
                    UsageEventRecord.model_profile,
                )
                .order_by(
                    (func.sum(UsageEventRecord.tokens_in) + func.sum(UsageEventRecord.tokens_out)).desc()
                )
            )
            if since is not None:
                q = q.where(UsageEventRecord.created_at >= since)
            rows = session.execute(q).all()
        return [
            {
                "principal_id": row.principal_id,
                "principal_email": row.principal_email,
                "model_profile": row.model_profile,
                "tokens_in": int(row.tokens_in),
                "tokens_out": int(row.tokens_out),
                "request_count": int(row.request_count),
            }
            for row in rows
        ]

    def total_for_user(self, user_id: str) -> int:
        with self._session_factory() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(UsageEventRecord.tokens_in + UsageEventRecord.tokens_out), 0))
                .where(UsageEventRecord.principal_id == user_id)
                .where(UsageEventRecord.status == "success")
            )
        return int(total or 0)

    def activity_for_user(self, user_id: str, days: int) -> list[dict]:
        since = datetime.now(UTC) - timedelta(days=days)
        with self._session_factory() as session:
            rows = session.execute(text("""
                SELECT
                    date_trunc('day', created_at) AS day,
                    SUM(tokens_in) as tokens_in,
                    SUM(tokens_out) as tokens_out,
                    COUNT(*) as request_count
                FROM usage_events
                WHERE principal_id = :uid AND created_at >= :since
                GROUP BY 1
                ORDER BY 1
            """), {"uid": user_id, "since": since}).fetchall()
        return [
            {
                "date": str(row.day.date()),
                "tokens_in": int(row.tokens_in),
                "tokens_out": int(row.tokens_out),
                "request_count": int(row.request_count),
            }
            for row in rows
        ]

    def activity_by_model_for_user(self, user_id: str, days: int) -> list[dict]:
        since = datetime.now(UTC) - timedelta(days=days)
        with self._session_factory() as session:
            rows = session.execute(text("""
                SELECT
                    model_profile,
                    SUM(tokens_in) as tokens_in,
                    SUM(tokens_out) as tokens_out,
                    COUNT(*) as request_count
                FROM usage_events
                WHERE principal_id = :uid AND created_at >= :since AND status = 'success'
                GROUP BY model_profile
                ORDER BY (SUM(tokens_in) + SUM(tokens_out)) DESC
            """), {"uid": user_id, "since": since}).fetchall()
        return [
            {
                "model_profile": row.model_profile,
                "tokens_in": int(row.tokens_in),
                "tokens_out": int(row.tokens_out),
                "request_count": int(row.request_count),
            }
            for row in rows
        ]

    def logs_for_user(self, user_id: str, limit: int, offset: int) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(text("""
                SELECT request_id, principal_id, model_profile, provider,
                       credential_id, tokens_in, tokens_out, latency_ms,
                       status, created_at
                FROM usage_events
                WHERE principal_id = :uid
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """), {"uid": user_id, "limit": limit, "offset": offset}).fetchall()
        return [
            {
                "request_id": row.request_id,
                "principal_id": row.principal_id,
                "model_profile": row.model_profile,
                "provider": row.provider,
                "credential_id": row.credential_id,
                "tokens_in": int(row.tokens_in),
                "tokens_out": int(row.tokens_out),
                "latency_ms": int(row.latency_ms),
                "status": row.status,
                "created_at": row.created_at.timestamp(),
            }
            for row in rows
        ]

    def total_for_team(self, team_id: str) -> int:
        with self._session_factory() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(UsageEventRecord.tokens_in + UsageEventRecord.tokens_out), 0))
                .join(UsageEventTeamRecord, UsageEventTeamRecord.request_id == UsageEventRecord.request_id)
                .where(UsageEventTeamRecord.team_id == team_id)
                .where(UsageEventRecord.status == "success")
            )
        return int(total or 0)
