from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException, status

from enterprise_llm_proxy.domain.credentials import CredentialState
from enterprise_llm_proxy.domain.credentials import ProviderCredential
from enterprise_llm_proxy.domain.inference import RoutingDecision, UnifiedInferenceRequest
from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.services.credentials import CredentialPoolService
from enterprise_llm_proxy.services.model_catalog import ModelCatalog


class RoutingService:
    def __init__(
        self,
        model_catalog: ModelCatalog,
        credential_pool: CredentialPoolService,
        system_openai_compat_model_checker=None,  # type: ignore[no-untyped-def]
    ) -> None:
        self._model_catalog = model_catalog
        self._credential_pool = credential_pool
        self._system_openai_compat_model_checker = system_openai_compat_model_checker

    def build_request(
        self,
        *,
        protocol: str,
        payload: dict[str, object],
        principal: Principal,
    ) -> UnifiedInferenceRequest:
        model_name = str(payload["model"])
        model_definition = self._model_catalog.resolve_model_for_principal(
            model_name, principal, self._credential_pool
        )
        supported_protocols = list(model_definition["supported_protocols"])
        if protocol not in supported_protocols:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model {model_name} does not support {protocol}",
            )
        return UnifiedInferenceRequest(
            request_id=f"req_{uuid4().hex}",
            protocol=protocol,
            model=model_name,
            model_profile=model_definition["model_profile"],
            upstream_model=str(model_definition["upstream_model"]),
            auth_modes=[str(mode) for mode in model_definition["auth_modes"]],
            provider=model_definition["provider"],
            provider_alias=(
                str(model_definition["provider_alias"])
                if model_definition.get("provider_alias")
                else None
            ),
            payload=payload,
            principal=principal,
            estimated_units=self._estimate_units(payload),
        )

    def select_credential(
        self,
        request: UnifiedInferenceRequest,
        *,
        excluded_ids: set[str] | None = None,
    ) -> tuple[ProviderCredential, RoutingDecision]:
        route_block: tuple[str, object] | None = None
        for auth_kind in request.auth_modes:
            prefer_overlay = (
                request.provider == "openai_compat"
                and self._system_openai_compat_model_checker is not None
                and self._system_openai_compat_model_checker(request.upstream_model)
            )
            credential = self._credential_pool.select(
                provider=request.provider,
                auth_kind=auth_kind,
                provider_alias=request.provider_alias,
                upstream_model=request.upstream_model,
                principal=request.principal,
                excluded_ids=excluded_ids or set(),
                prefer_overlay=prefer_overlay,
            )
            if credential is None:
                block = self._credential_pool.diagnose_route_block(
                    provider=request.provider,
                    auth_kind=auth_kind,
                    provider_alias=request.provider_alias,
                    upstream_model=request.upstream_model,
                    principal=request.principal,
                )
                if block is not None:
                    if route_block is None:
                        route_block = (auth_kind, block)
                    else:
                        _blocked_auth_kind, previous_block = route_block
                        if (
                            getattr(previous_block, "reason", None) == "unbound"
                            and block.reason != "unbound"
                        ):
                            route_block = (auth_kind, block)
                continue
            executor = self._executor_for(request, credential)
            return credential, RoutingDecision(
                protocol=request.protocol,
                provider=request.provider,
                model_profile=request.model_profile,
                executor=executor,
                credential_id=credential.id,
            )

        if route_block is not None:
            _auth_kind, block = route_block
            detail = self._format_route_block_detail(request.provider, block)
            headers = self._route_block_headers(block)
            raise HTTPException(
                status_code=self._route_block_status(block),
                detail=detail,
                headers=headers,
            )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No route available for {request.provider}",
        )

    @staticmethod
    def _format_route_block_detail(provider: str, block: object) -> str:
        reason = getattr(block, "reason", None)
        state = getattr(block, "state", None)
        credential_count = int(getattr(block, "credential_count", 0) or 0)
        retry_at = getattr(block, "retry_at", None)
        provider_label = provider
        if reason == "unbound":
            return (
                f"No {provider_label} upstream credentials are bound or visible "
                "for this principal"
            )
        if reason == "saturated":
            return (
                f"All {credential_count} available {provider_label} upstream credentials are "
                "busy / leases saturated"
            )
        if state == CredentialState.RATE_LIMITED:
            return (
                f"All {credential_count} available {provider_label} upstream credentials are "
                "rate_limited by the provider"
            )
        if retry_at is not None:
            return (
                f"All {credential_count} available {provider_label} upstream credentials are in "
                f"cooldown until {retry_at.isoformat()}"
            )
        return f"All {credential_count} available {provider_label} upstream credentials are in cooldown"

    @staticmethod
    def _route_block_status(block: object) -> int:
        if getattr(block, "reason", None) in {"saturated", "unbound"}:
            return status.HTTP_503_SERVICE_UNAVAILABLE
        return status.HTTP_429_TOO_MANY_REQUESTS

    @staticmethod
    def _route_block_headers(block: object) -> dict[str, str] | None:
        retry_at = getattr(block, "retry_at", None)
        if retry_at is None:
            return None
        now = datetime.now(UTC)
        retry_after = max(0, int((retry_at - now).total_seconds()))
        return {"Retry-After": str(retry_after)}

    @staticmethod
    def _executor_for(
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> str:
        if request.provider == "openai-codex":
            return "oauth_bridge"
        if request.provider == "openai_compat":
            return "openai_compat"
        if request.protocol == "anthropic_messages" and request.provider == "openai":
            return "oauth_bridge"
        if credential.auth_kind in {
            "oauth_subscription",
            "codex_chatgpt_oauth_managed",
            "codex_chatgpt_oauth_imported",
        }:
            return "oauth_bridge"
        return "litellm"

    @staticmethod
    def _estimate_units(payload: dict[str, object]) -> int:
        for key in ("max_output_tokens", "max_tokens"):
            value = payload.get(key)
            if isinstance(value, int):
                return max(1, value)
        return 1
