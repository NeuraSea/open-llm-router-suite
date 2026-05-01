from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException, status

from enterprise_llm_proxy.domain.credentials import ProviderCredential
from enterprise_llm_proxy.domain.inference import UnifiedInferenceRequest


@dataclass(frozen=True)
class ExecutionResult:
    body: dict[str, object]
    tokens_in: int
    tokens_out: int


class Executor(Protocol):
    def execute(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> ExecutionResult:
        ...


class UpstreamRateLimitError(RuntimeError):
    """Raised when an upstream subscription or API key is rate limited."""


class UpstreamCredentialInvalidError(RuntimeError):
    """Raised when an upstream credential is invalid and should be disabled."""


INVALID_CREDENTIAL_STATUSES = frozenset(
    {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    }
)


def is_invalid_credential_status(status_code: int) -> bool:
    return status_code in INVALID_CREDENTIAL_STATUSES


class MissingExecutor:
    def __init__(self, name: str) -> None:
        self._name = name

    def execute(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> ExecutionResult:
        del request
        del credential
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{self._name} executor is not configured",
        )
