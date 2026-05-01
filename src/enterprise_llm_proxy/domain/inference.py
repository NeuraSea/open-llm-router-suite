from __future__ import annotations

from dataclasses import dataclass
from time import time

from enterprise_llm_proxy.domain.models import Principal


@dataclass(frozen=True)
class UnifiedInferenceRequest:
    request_id: str
    protocol: str
    model: str
    model_profile: str
    upstream_model: str
    auth_modes: list[str]
    provider: str
    payload: dict[str, object]
    principal: Principal
    estimated_units: int
    provider_alias: str | None = None


@dataclass(frozen=True)
class RoutingDecision:
    protocol: str
    provider: str
    model_profile: str
    executor: str
    credential_id: str


@dataclass(frozen=True)
class UsageEvent:
    request_id: str
    principal_id: str
    model_profile: str
    provider: str
    credential_id: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    status: str
    created_at: float
    principal_email: str | None = None

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        principal_id: str,
        model_profile: str,
        provider: str,
        credential_id: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        status: str,
        principal_email: str | None = None,
    ) -> "UsageEvent":
        return cls(
            request_id=request_id,
            principal_id=principal_id,
            principal_email=principal_email,
            model_profile=model_profile,
            provider=provider,
            credential_id=credential_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            status=status,
            created_at=time(),
        )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "principal_id": self.principal_id,
            "principal_email": self.principal_email,
            "model_profile": self.model_profile,
            "provider": self.provider,
            "credential_id": self.credential_id,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "created_at": self.created_at,
        }
