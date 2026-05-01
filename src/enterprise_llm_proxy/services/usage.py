from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from enterprise_llm_proxy.domain.inference import UsageEvent


class UsageLedger:
    def __init__(self, repository=None) -> None:  # type: ignore[no-untyped-def]
        self._repository = repository
        self._events: list[UsageEvent] = []
        self._team_memberships: dict[str, list[str]] = {}

    def record(self, event: UsageEvent, *, team_ids: list[str]) -> None:
        if self._repository is not None:
            self._repository.record(event, team_ids=team_ids)
            return
        self._events.append(event)
        self._team_memberships[event.request_id] = team_ids

    def list_events(self) -> list[UsageEvent]:
        if self._repository is not None:
            return self._repository.list_events()
        return list(reversed(self._events))

    def total_for_user(self, user_id: str) -> int:
        if self._repository is not None:
            return self._repository.total_for_user(user_id)
        return sum(
            event.tokens_in + event.tokens_out
            for event in self._events
            if event.principal_id == user_id and event.status == "success"
        )

    def total_for_team(self, team_id: str) -> int:
        if self._repository is not None:
            return self._repository.total_for_team(team_id)
        return sum(
            event.tokens_in + event.tokens_out
            for event in self._events
            if team_id in self._team_memberships.get(event.request_id, [])
            and event.status == "success"
        )

    def activity_for_user(self, user_id: str, days: int) -> list[dict]:
        if self._repository is not None:
            return self._repository.activity_for_user(user_id, days)
        return []

    def activity_by_model_for_user(self, user_id: str, days: int) -> list[dict]:
        if self._repository is not None:
            return self._repository.activity_by_model_for_user(user_id, days)
        return []

    def logs_for_user(self, user_id: str, limit: int, offset: int) -> list[dict]:
        if self._repository is not None:
            return self._repository.logs_for_user(user_id, limit, offset)
        return []

    def summarize_usage(self, since: datetime | None) -> list[dict]:
        if self._repository is not None:
            return self._repository.summarize_usage(since)
        # In-memory fallback
        groups: dict[tuple[str, str | None, str], dict] = defaultdict(
            lambda: {"tokens_in": 0, "tokens_out": 0, "request_count": 0, "principal_email": None}
        )
        for event in self._events:
            if event.status != "success":
                continue
            if since is not None:
                event_dt = datetime.fromtimestamp(event.created_at, tz=UTC)
                if event_dt < since:
                    continue
            key = (event.principal_id, event.principal_email, event.model_profile)
            groups[key]["tokens_in"] += event.tokens_in
            groups[key]["tokens_out"] += event.tokens_out
            groups[key]["request_count"] += 1
            groups[key]["principal_email"] = event.principal_email

        result = [
            {
                "principal_id": pid,
                "principal_email": g["principal_email"],
                "model_profile": model,
                "tokens_in": g["tokens_in"],
                "tokens_out": g["tokens_out"],
                "request_count": g["request_count"],
            }
            for (pid, _email, model), g in groups.items()
        ]
        result.sort(key=lambda r: r["tokens_in"] + r["tokens_out"], reverse=True)  # type: ignore[operator]
        return result
