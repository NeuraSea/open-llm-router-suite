from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status

from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.services.usage import UsageLedger


@dataclass(frozen=True)
class QuotaRule:
    scope_type: str
    scope_id: str
    limit: int

    def to_public_dict(self) -> dict[str, object]:
        return {
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "limit": self.limit,
        }


class QuotaService:
    def __init__(self, usage_ledger: UsageLedger, repository=None) -> None:  # type: ignore[no-untyped-def]
        self._usage_ledger = usage_ledger
        self._repository = repository
        self._quotas: dict[tuple[str, str], QuotaRule] = {}

    def set_quota(self, *, scope_type: str, scope_id: str, limit: int) -> QuotaRule:
        if self._repository is not None:
            return self._repository.set_quota(scope_type=scope_type, scope_id=scope_id, limit=limit)
        rule = QuotaRule(scope_type=scope_type, scope_id=scope_id, limit=limit)
        self._quotas[(scope_type, scope_id)] = rule
        return rule

    def list_quotas(self) -> list[QuotaRule]:
        if self._repository is not None:
            return self._repository.list_quotas()
        return sorted(self._quotas.values(), key=lambda item: (item.scope_type, item.scope_id))

    def ensure_capacity(self, principal: Principal, estimated_units: int) -> None:
        user_rule = (
            self._repository.get_quota(scope_type="user", scope_id=principal.user_id)
            if self._repository is not None
            else self._quotas.get(("user", principal.user_id))
        )
        if user_rule is not None:
            if self._usage_ledger.total_for_user(principal.user_id) + estimated_units > user_rule.limit:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Quota exceeded",
                )

        for team_id in principal.team_ids:
            team_rule = (
                self._repository.get_quota(scope_type="team", scope_id=team_id)
                if self._repository is not None
                else self._quotas.get(("team", team_id))
            )
            if team_rule is not None:
                if self._usage_ledger.total_for_team(team_id) + estimated_units > team_rule.limit:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Quota exceeded",
                    )
