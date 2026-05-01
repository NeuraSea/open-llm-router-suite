from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlparse

import jwt as pyjwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.db import create_engine_from_settings, create_session_factory

from enterprise_llm_proxy.domain.credentials import CredentialState, CredentialVisibility
from enterprise_llm_proxy.domain.inference import UnifiedInferenceRequest, UsageEvent
from enterprise_llm_proxy.domain.models import Principal
from enterprise_llm_proxy.repositories.api_keys import PostgresPlatformApiKeyRepository
from enterprise_llm_proxy.repositories.cli_auth import (
    PostgresCliAuthRepository,
    _InMemoryRevokedTokenRepository,
    RevokedTokenRepository,
)
from enterprise_llm_proxy.repositories.credentials import PostgresCredentialRepository
from enterprise_llm_proxy.repositories.issued_tokens import (
    PostgresIssuedTokenRepository,
    _InMemoryIssuedTokenRepository,
    IssuedTokenRow,
)
from enterprise_llm_proxy.repositories.quotas import PostgresQuotaRepository
from enterprise_llm_proxy.repositories.preferences import (
    InMemoryUserPreferencesRepository,
    PostgresUserPreferencesRepository,
)
from enterprise_llm_proxy.repositories.usage import PostgresUsageRepository
from enterprise_llm_proxy.security import PassthroughSecretCodec
from enterprise_llm_proxy.services.api_keys import PlatformApiKeyService
from enterprise_llm_proxy.services.bootstrap import BootstrapScriptService
from enterprise_llm_proxy.services.compat_models import (
    COMPAT_PROVIDERS,
    CompatModelDiscoveryError,
    discover_compat_models,
    normalize_provider_alias,
    validate_provider_alias,
)
from enterprise_llm_proxy.services.credentials import CredentialPoolService, CredentialRefresher
from enterprise_llm_proxy.services.execution import Executor, MissingExecutor, UpstreamRateLimitError
from enterprise_llm_proxy.services.execution import UpstreamCredentialInvalidError
from enterprise_llm_proxy.services.litellm_executor import LiteLLMExecutor
from enterprise_llm_proxy.services.feishu import FeishuOidcClient
from enterprise_llm_proxy.services.identity import IdentityService, OidcClient
from enterprise_llm_proxy.services.lm_studio import LMStudioService
from enterprise_llm_proxy.services.model_catalog import ModelCatalog
from enterprise_llm_proxy.services.newapi import NewApiClient, NewApiCredentialSyncService
from enterprise_llm_proxy.services.oidc import GenericOidcClient
from enterprise_llm_proxy.services.openai_compat_executor import OpenAICompatExecutor
from enterprise_llm_proxy.services.openai_bridge import OAuthBridgeExecutorRouter
from enterprise_llm_proxy.services.pages import (
    build_identity_provider_authorize_url,
    load_spa_index_html,
    resolve_ui_dist_dir,
)
from enterprise_llm_proxy.services.quotas import QuotaService
from enterprise_llm_proxy.services.routerctl_distribution import RouterctlDistributionService
from enterprise_llm_proxy.services.routing import RoutingService
from enterprise_llm_proxy.services.sso import RouterSsoAssertionService, RouterSsoAssertionSettings
from enterprise_llm_proxy.services.upstream_oauth import (
    CodexOAuthBroker,
    CodexOAuthCredentialRefresher,
    MissingCodexOAuthBroker,
    OpenAICodexOAuthBroker,
)
from enterprise_llm_proxy.services.usage import UsageLedger


# Re-export for tests
__all__ = [
    "create_app",
    "_InMemoryCliAuthRepository",
    "_InMemoryRevokedTokenRepository",
]


class _InMemoryCliAuthRepository:
    """In-memory CLI auth repository for tests and no-DB deployments."""

    def __init__(self) -> None:
        self._consumed_jtis: dict[str, datetime] = {}
        self._pending_logins: dict[str, tuple[dict, datetime]] = {}
        self._pending_codes: dict[str, tuple[dict, datetime]] = {}

    @staticmethod
    def _is_expired(expires_at: datetime, *, now: datetime) -> bool:
        exp = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
        return exp <= now

    def consume_jti(self, *, jti: str, expires_at: datetime) -> bool:
        """Atomically mark JTI as consumed. Returns True if first consumption."""
        if jti in self._consumed_jtis:
            return False
        self._consumed_jtis[jti] = expires_at
        return True

    def put_pending_login(
        self,
        *,
        login_id: str,
        payload: dict,
        expires_at: datetime,
    ) -> None:
        self._pending_logins[login_id] = (payload, expires_at)

    def get_pending_login(self, *, login_id: str) -> dict | None:
        entry = self._pending_logins.get(login_id)
        if entry is None:
            return None
        payload, expires_at = entry
        now = datetime.now(UTC)
        if self._is_expired(expires_at, now=now):
            del self._pending_logins[login_id]
            return None
        return payload

    def pop_pending_login(self, *, login_id: str) -> dict | None:
        entry = self._pending_logins.pop(login_id, None)
        if entry is None:
            return None
        payload, expires_at = entry
        now = datetime.now(UTC)
        if self._is_expired(expires_at, now=now):
            return None
        return payload

    def put_pending_code(
        self,
        *,
        code: str,
        payload: dict,
        expires_at: datetime,
    ) -> None:
        self._pending_codes[code] = (payload, expires_at)

    def pop_pending_code(self, *, code: str) -> dict | None:
        entry = self._pending_codes.pop(code, None)
        if entry is None:
            return None
        payload, expires_at = entry
        now = datetime.now(UTC)
        if self._is_expired(expires_at, now=now):
            return None
        return payload

    def put_codex_oauth_principal(
        self,
        *,
        state: str,
        principal: Principal,
        expires_at: datetime,
    ) -> None:
        self._pending_logins[f"codex_oauth:{state}"] = ({"principal": principal}, expires_at)

    def pop_codex_oauth_principal(self, *, state: str) -> Principal | None:
        key = f"codex_oauth:{state}"
        entry = self._pending_logins.pop(key, None)
        if entry is None:
            return None
        payload, expires_at = entry
        now = datetime.now(UTC)
        if self._is_expired(expires_at, now=now):
            return None
        return payload.get("principal")

    def sweep_expired(self) -> None:
        now = datetime.now(UTC)
        self._consumed_jtis = {
            jti: expires_at
            for jti, expires_at in self._consumed_jtis.items()
            if not self._is_expired(expires_at, now=now)
        }
        self._pending_logins = {
            login_id: entry
            for login_id, entry in self._pending_logins.items()
            if not self._is_expired(entry[1], now=now)
        }
        self._pending_codes = {
            code: entry
            for code, entry in self._pending_codes.items()
            if not self._is_expired(entry[1], now=now)
        }


def create_app(
    settings: AppSettings | None = None,
    oidc_client: OidcClient | None = None,
    credential_refresher: CredentialRefresher | None = None,
    litellm_executor: Executor | None = None,
    openai_compat_executor: Executor | None = None,
    oauth_bridge_executor: Executor | None = None,
    codex_oauth_broker: CodexOAuthBroker | None = None,
    cli_auth_repository: "_InMemoryCliAuthRepository | None" = None,
    issued_token_repo: "_InMemoryIssuedTokenRepository | None" = None,
    revoked_token_repo: "_InMemoryRevokedTokenRepository | None" = None,
    distribution_service: "RouterctlDistributionService | None" = None,
    usage_ledger: "UsageLedger | None" = None,
    lmstudio_service: "LMStudioService | None" = None,
    newapi_client: "NewApiClient | None" = None,
) -> FastAPI:
    settings = settings or AppSettings()

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):  # noqa: ARG001
        sweep_task: asyncio.Task | None = None
        if settings.database_url:
            sweep_interval_seconds = max(
                60,
                min(settings.credential_lease_ttl_seconds, 300),
            )
            try:
                credential_pool.reset_stale_leases(
                    max_age_seconds=settings.credential_lease_ttl_seconds
                )
            except Exception:
                logging.getLogger(__name__).exception("reset_stale_leases failed")

            async def _sweep_loop() -> None:
                _log = logging.getLogger(__name__)
                while True:
                    await asyncio.sleep(sweep_interval_seconds)
                    try:
                        resolved_cli_auth_repo.sweep_expired()  # type: ignore[union-attr]
                        credential_pool.reset_stale_leases(
                            max_age_seconds=settings.credential_lease_ttl_seconds
                        )
                    except Exception:
                        _log.exception("background sweep failed")

            sweep_task = asyncio.create_task(_sweep_loop())
        try:
            yield
        finally:
            if sweep_task is not None:
                sweep_task.cancel()
                try:
                    await sweep_task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="Enterprise LLM Proxy", lifespan=lifespan)
    ui_dist_dir = resolve_ui_dist_dir()
    spa_index_html = load_spa_index_html()
    resolved_oidc_client = oidc_client
    if (
        resolved_oidc_client is None
        and settings.oidc_client_id
        and settings.oidc_client_secret
        and settings.oidc_token_url
        and settings.oidc_userinfo_url
    ):
        resolved_oidc_client = GenericOidcClient(settings=settings)
    elif (
        resolved_oidc_client is None
        and settings.feishu_client_id
        and settings.feishu_client_secret
        and settings.feishu_token_url
        and settings.feishu_userinfo_url
    ):
        resolved_oidc_client = FeishuOidcClient(settings=settings)
    identity_service = IdentityService(
        signing_secret=settings.jwt_signing_secret,
        oidc_client=resolved_oidc_client,
    )
    sso_assertion_service = RouterSsoAssertionService(
        RouterSsoAssertionSettings(
            issuer=settings.router_sso_issuer,
            audience=settings.router_sso_audience,
            private_key_pem=settings.router_sso_private_key_pem,
            private_key_path=settings.router_sso_private_key_path,
            ttl_seconds=settings.router_sso_assertion_ttl_seconds,
        )
    )
    newapi_sync_service = NewApiCredentialSyncService(
        settings=settings,
        client=newapi_client,
    )
    resolved_codex_oauth_broker = codex_oauth_broker
    if (
        resolved_codex_oauth_broker is None
        and settings.codex_oauth_client_id
        and settings.codex_oauth_client_secret
        and settings.codex_oauth_redirect_uri
    ):
        resolved_codex_oauth_broker = OpenAICodexOAuthBroker(settings)
    resolved_codex_oauth_broker = resolved_codex_oauth_broker or MissingCodexOAuthBroker()

    credential_repository = None
    quota_repository = None
    usage_repository = None
    api_key_repository = None
    preferences_repository = None
    session_factory = None
    if settings.database_url:
        engine = create_engine_from_settings(settings)
        session_factory = create_session_factory(engine)
        secret_codec = PassthroughSecretCodec()
        credential_repository = PostgresCredentialRepository(
            session_factory=session_factory,
            secret_codec=secret_codec,
        )
        quota_repository = PostgresQuotaRepository(session_factory=session_factory)
        usage_repository = PostgresUsageRepository(session_factory=session_factory)
        api_key_repository = PostgresPlatformApiKeyRepository(session_factory=session_factory)
        preferences_repository = PostgresUserPreferencesRepository(session_factory=session_factory)

    # CLI auth, issued tokens, and revoked tokens use in-memory fallback by default.
    # For production persistence, pass Postgres-backed repos explicitly via create_app params.
    resolved_cli_auth_repo: _InMemoryCliAuthRepository | PostgresCliAuthRepository = (
        cli_auth_repository or _InMemoryCliAuthRepository()
    )
    resolved_issued_token_repo: _InMemoryIssuedTokenRepository | PostgresIssuedTokenRepository = (
        issued_token_repo or _InMemoryIssuedTokenRepository()
    )
    resolved_revoked_token_repo: _InMemoryRevokedTokenRepository | RevokedTokenRepository = (
        revoked_token_repo or _InMemoryRevokedTokenRepository()
    )

    resolved_preferences_repo = preferences_repository or InMemoryUserPreferencesRepository()

    def _load_custom_models() -> list[dict]:
        from enterprise_llm_proxy.repositories.models import CustomModelRecord

        with session_factory() as session:  # type: ignore[misc]
            rows = (
                session.query(CustomModelRecord)
                .filter(CustomModelRecord.enabled == True)  # noqa: E712
                .all()
            )
            return [
                {
                    "id": r.id,
                    "display_name": r.display_name,
                    "provider": r.provider,
                    "model_profile": r.model_profile,
                    "upstream_model": r.upstream_model,
                    "description": r.description,
                    "auth_modes": list(r.auth_modes),
                    "supported_clients": list(r.supported_clients),
                }
                for r in rows
            ]

    resolved_lmstudio_service = lmstudio_service
    if resolved_lmstudio_service is None and settings.lm_studio_enabled:
        resolved_lmstudio_service = LMStudioService(settings)
    overlay_credentials = []
    if resolved_lmstudio_service is not None:
        system_credential = resolved_lmstudio_service.build_system_credential()
        if system_credential is not None:
            overlay_credentials.append(system_credential)

    model_catalog = ModelCatalog(
        custom_models_loader=_load_custom_models if session_factory else None,
        compat_models_loader=(
            resolved_lmstudio_service.list_models if resolved_lmstudio_service is not None else None
        ),
    )

    def _normalize_available_models(raw_models: object) -> list[str]:
        if not isinstance(raw_models, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_model in raw_models:
            model_id = str(raw_model).strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            normalized.append(model_id)
        return normalized

    def _merge_available_models(
        existing_catalog_info: dict | None,
        available_models: list[str],
    ) -> dict | None:
        if not available_models:
            return existing_catalog_info
        merged = dict(existing_catalog_info or {})
        merged["available_models"] = available_models
        return merged

    def _validate_compat_alias_conflicts(
        *,
        provider_alias: str,
        principal: Principal,
    ) -> None:
        validate_provider_alias(provider_alias)
        for credential in [*credential_pool.list_credentials(), *credential_pool.list_for_owner(principal.user_id)]:
            if getattr(credential, "provider", None) not in COMPAT_PROVIDERS:
                continue
            existing_alias = getattr(credential, "provider_alias", None)
            if existing_alias != provider_alias:
                continue
            if credential.visibility == CredentialVisibility.ENTERPRISE_POOL:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"provider_alias already exists in enterprise pool: {provider_alias}",
                )
            if credential.owner_principal_id == principal.user_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"provider_alias already exists for current user: {provider_alias}",
                )

    resolved_credential_refresher = CodexOAuthCredentialRefresher(
        resolved_codex_oauth_broker,
        fallback=credential_refresher,
    )
    credential_pool = CredentialPoolService(
        refresher=resolved_credential_refresher,
        repository=credential_repository,
        overlay_credentials=overlay_credentials,
    )
    resolved_usage_ledger = usage_ledger or UsageLedger(repository=usage_repository)
    quota_service = QuotaService(resolved_usage_ledger, repository=quota_repository)
    routing_service = RoutingService(
        model_catalog,
        credential_pool,
        system_openai_compat_model_checker=(
            resolved_lmstudio_service.has_model if resolved_lmstudio_service is not None else None
        ),
    )
    api_key_service = PlatformApiKeyService(repository=api_key_repository)
    bootstrap_service = BootstrapScriptService(settings)
    resolved_distribution_service = distribution_service or RouterctlDistributionService(
        wheel_dir=settings.routerctl_wheel_dir
    )
    executors = {
        "litellm": litellm_executor or LiteLLMExecutor(),
        "openai_compat": openai_compat_executor or OpenAICompatExecutor(),
        "oauth_bridge": oauth_bridge_executor or OAuthBridgeExecutorRouter(settings),
    }

    class _CredentialLease:
        def __init__(self, credential_id: str) -> None:
            self._credential_id = credential_id
            self._released = False

        def release(self) -> None:
            if self._released:
                return
            self._released = True
            credential_pool.release(self._credential_id)

        def mark_cooldown(self, *, seconds: int) -> None:
            if self._released:
                return
            try:
                credential_pool.mark_cooldown(self._credential_id, seconds=seconds)
            except Exception:
                credential_pool.release(self._credential_id)
                self._released = True
                raise
            self._released = True

        def mark_disabled(self) -> None:
            if self._released:
                return
            try:
                credential_pool.mark_disabled(self._credential_id)
            except Exception:
                credential_pool.release(self._credential_id)
                self._released = True
                raise
            self._released = True

    def _credential_route_status(
        model: dict[str, object],
        principal: Principal,
    ) -> tuple[bool, str | None]:
        provider = str(model.get("provider", ""))
        provider_alias = model.get("provider_alias")
        provider_alias_value = (
            str(provider_alias)
            if isinstance(provider_alias, str) and provider_alias
            else None
        )
        auth_modes = [str(mode) for mode in model.get("auth_modes", [])]
        for auth_kind in auth_modes:
            if credential_pool.has_available(
                provider=provider,
                auth_kind=auth_kind,
                provider_alias=provider_alias_value,
                principal=principal,
            ):
                return True, None

        for auth_kind in auth_modes:
            block = credential_pool.diagnose_route_block(
                provider=provider,
                auth_kind=auth_kind,
                provider_alias=provider_alias_value,
                principal=principal,
            )
            if block is not None:
                if block.reason == "unbound":
                    continue
                return False, RoutingService._format_route_block_detail(provider, block)
        return False, None

    if ui_dist_dir is not None and (ui_dist_dir / "assets").exists():
        app.mount(
            "/portal/assets",
            StaticFiles(directory=ui_dist_dir / "assets"),
            name="portal-assets",
        )

    def extract_token(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
    ) -> str:
        if authorization and authorization.startswith("Bearer "):
            return authorization.removeprefix("Bearer ").strip()
        if x_api_key:
            return x_api_key.strip()

        cookie_token = request.cookies.get(settings.session_cookie_name)
        if cookie_token:
            return cookie_token

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    def authenticate_auth_token(token: str):
        if token.startswith("elp_"):
            principal = api_key_service.authenticate(token)
            from enterprise_llm_proxy.services.identity import AuthenticatedToken
            return AuthenticatedToken(
                principal=principal,
                kind="platform_api_key",
                claims=principal.to_dict(),
            )
        auth_token = identity_service.authenticate_token(token)
        jti = str(auth_token.claims.get("jti", ""))
        if jti and resolved_revoked_token_repo.is_revoked(jti):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )
        return auth_token

    def authenticate_token(token: str) -> Principal:
        return authenticate_auth_token(token).principal

    def require_principal(token: str = Depends(extract_token)) -> Principal:
        return authenticate_token(token)

    def require_cli_session(token: str = Depends(extract_token)) -> Principal:
        auth_token = authenticate_auth_token(token)
        if auth_token.kind != "cli_session":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CLI session required",
            )
        return auth_token.principal

    def require_admin(principal: Principal = Depends(require_principal)) -> Principal:
        if principal.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin role required",
            )
        return principal

    def optional_principal(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
    ) -> Principal | None:
        token: str | None = None
        if authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
        elif x_api_key:
            token = x_api_key.strip()
        else:
            token = request.cookies.get(settings.session_cookie_name)
        if not token:
            return None
        try:
            return authenticate_token(token)
        except HTTPException:
            return None

    def safe_return_to(raw_return_to: str | None) -> str:
        if not raw_return_to:
            return "/"
        candidate = raw_return_to.strip()
        if not candidate:
            return "/"
        parsed = urlparse(candidate)
        if not parsed.scheme and not parsed.netloc and candidate.startswith("/"):
            return candidate
        public_host = urlparse(settings.router_public_base_url).hostname
        allowed_hosts = {
            host.strip().lower()
            for host in [public_host, *settings.sso_return_to_allowed_hosts]
            if host and host.strip()
        }
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.hostname.lower() in allowed_hosts
        ):
            return candidate
        return "/"

    def browser_session_response(principal: Principal, redirect_target: str) -> RedirectResponse:
        access_token = identity_service.issue_access_token(principal)
        response = RedirectResponse(
            url=redirect_target,
            status_code=status.HTTP_303_SEE_OTHER,
        )
        response.set_cookie(
            key=settings.session_cookie_name,
            value=access_token,
            httponly=True,
            samesite="lax",
            secure=settings.session_cookie_secure,
            max_age=settings.session_cookie_max_age_seconds,
            path="/",
            domain=settings.session_cookie_domain,
        )
        return response

    def sync_newapi_credential(
        credential_id: str,
        principal: Principal,
        *,
        shared: bool | None = None,
    ) -> None:
        credential = credential_pool.get_credential(credential_id)
        if credential is None:
            return
        try:
            newapi_sync_service.sync_credential(
                credential,
                principal,
                shared=shared,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "new-api credential sync failed for %s",
                credential_id,
            )

    def sync_principal_for_credential(
        credential,
        fallback: Principal,
    ) -> Principal:  # type: ignore[no-untyped-def]
        if not credential.owner_principal_id:
            return fallback
        if credential.owner_principal_id == fallback.user_id:
            return fallback
        return Principal(
            user_id=credential.owner_principal_id,
            email="",
            name=credential.owner_principal_id,
            team_ids=[],
            role="member",
        )

    def principal_for_stored_credential(credential) -> Principal:  # type: ignore[no-untyped-def]
        owner = credential.owner_principal_id or credential.account_id
        email = owner if "@" in owner else ""
        return Principal(
            user_id=owner,
            email=email,
            name=owner,
            team_ids=[],
            role="member",
        )

    def bridge_api_key_from_headers(
        authorization: str | None,
        x_api_key: str | None,
    ) -> str | None:
        if x_api_key:
            return x_api_key.strip()
        if not authorization:
            return None
        value = authorization.strip()
        if value.startswith("Bearer "):
            return value.removeprefix("Bearer ").strip()
        return value

    def require_bridge_upstream_key(
        authorization: str | None,
        x_api_key: str | None,
    ) -> None:
        expected = settings.bridge_upstream_api_key
        supplied = bridge_api_key_from_headers(authorization, x_api_key)
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bridge upstream authentication required",
            )

    def newapi_anthropic_bridge_request(
        payload: dict[str, object],
        credential,
    ) -> UnifiedInferenceRequest:  # type: ignore[no-untyped-def]
        raw_model = str(payload.get("model") or settings.default_claude_model)
        upstream_model = raw_model
        for prefix in ("claude-max/", "anthropic/"):
            if upstream_model.startswith(prefix):
                upstream_model = upstream_model.removeprefix(prefix)
        principal = Principal(
            user_id=credential.owner_principal_id or "new-api-bridge",
            email="",
            name=credential.owner_principal_id or "new-api-bridge",
            team_ids=[],
            role="member",
        )
        return UnifiedInferenceRequest(
            request_id=f"bridge_{secrets.token_urlsafe(12)}",
            protocol="anthropic_messages",
            model=raw_model,
            model_profile=f"anthropic/{upstream_model}",
            upstream_model=upstream_model,
            auth_modes=[credential.auth_kind],
            provider="claude-max",
            payload=payload,
            principal=principal,
            estimated_units=1,
            provider_alias=credential.provider_alias,
        )

    def newapi_openai_codex_bridge_request(
        protocol: str,
        payload: dict[str, object],
        credential,
    ) -> UnifiedInferenceRequest:  # type: ignore[no-untyped-def]
        raw_model = str(payload.get("model") or settings.default_codex_model)
        upstream_model = raw_model
        for prefix in ("openai-codex/", "codex/"):
            if upstream_model.startswith(prefix):
                upstream_model = upstream_model.removeprefix(prefix)
        principal = Principal(
            user_id=credential.owner_principal_id or "new-api-bridge",
            email="",
            name=credential.owner_principal_id or "new-api-bridge",
            team_ids=[],
            role="member",
        )
        return UnifiedInferenceRequest(
            request_id=f"bridge_{secrets.token_urlsafe(12)}",
            protocol=protocol,
            model=raw_model,
            model_profile=f"openai-codex/{upstream_model}",
            upstream_model=upstream_model,
            auth_modes=[credential.auth_kind],
            provider="openai-codex",
            payload=payload,
            principal=principal,
            estimated_units=1,
            provider_alias=credential.provider_alias,
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False, response_model=None)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/portal", status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    @app.get(
        "/feishu/launch",
        response_class=HTMLResponse,
        include_in_schema=False,
        response_model=None,
    )
    async def feishu_launch() -> HTMLResponse:
        return HTMLResponse(spa_index_html)

    @app.get("/sso/login", include_in_schema=False, response_model=None)
    async def sso_login(return_to: str | None = None) -> RedirectResponse:
        state = f"sso:{secrets.token_urlsafe(16)}"
        resolved_cli_auth_repo.put_pending_login(
            login_id=state,
            payload={"return_to": safe_return_to(return_to)},
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
        authorize_url = build_identity_provider_authorize_url(settings, state=state)
        if not authorize_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SSO identity provider is not configured",
            )
        return RedirectResponse(url=authorize_url, status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/sso/assertion", include_in_schema=False, response_model=None)
    async def sso_assertion(principal: Principal = Depends(require_principal)) -> Response:
        try:
            assertion = sso_assertion_service.issue(principal)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            )
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={
                "X-Router-SSO-Assertion": assertion,
                "X-Router-SSO-User": principal.user_id,
                "Cache-Control": "no-store",
            },
        )

    @app.get("/ui/config")
    async def ui_config() -> dict[str, object]:
        control_plane_base_url = bootstrap_service.control_plane_base_url()
        return {
            "app_name": "企业级 LLM Router 控制台",
            "router_public_base_url": settings.router_public_base_url,
            "router_control_plane_base_url": control_plane_base_url,
            "routerctl_install_url": bootstrap_service.routerctl_install_url(),
            "routerctl_windows_install_url": bootstrap_service.routerctl_powershell_install_url(),
            "default_claude_model": settings.default_claude_model,
            "default_codex_model": settings.default_codex_model,
            "platform_api_key_env": settings.platform_api_key_env,
            "feishu_authorize_url": build_identity_provider_authorize_url(settings),
            "codex_oauth_browser_enabled": bool(
                settings.codex_oauth_client_id
                and settings.codex_oauth_client_secret
                and settings.codex_oauth_redirect_uri
            ),
        }

    @app.get("/ui/models")
    async def ui_models(
        routable_only: bool = False,
        principal: Principal | None = Depends(optional_principal),
    ) -> dict[str, list[dict[str, object]]]:
        if principal is not None:
            return {
                "data": model_catalog.list_models_for_principal(
                    principal,
                    credential_pool,
                    routable_only=routable_only,
                )
            }
        return {"data": model_catalog.list_ui_models()}

    @app.get("/ui/session")
    async def ui_session(principal: Principal = Depends(require_principal)) -> dict[str, object]:
        return principal.to_dict()

    @app.post("/auth/oidc/callback")
    async def oidc_callback(payload: dict[str, str]) -> dict[str, object]:
        principal = identity_service.authenticate_code(payload["code"])
        access_token = identity_service.issue_access_token(principal)
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "principal": principal.to_dict(),
        }

    @app.get("/auth/oidc/callback", include_in_schema=False, response_model=None)
    async def oidc_callback_browser(
        code: str | None = None,
        state: str | None = None,
    ) -> RedirectResponse:
        if not code:
            return RedirectResponse(
                url="/feishu/launch",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        principal = identity_service.authenticate_code(code)

        # CLI PKCE flow: state encodes "cli:{login_id}"
        if state and state.startswith("cli:"):
            login_id = state[len("cli:"):]
            pending = resolved_cli_auth_repo.get_pending_login(login_id=login_id)
            if pending is not None:
                auth_code = secrets.token_urlsafe(24)
                expires_at_code = datetime.now(UTC) + timedelta(minutes=5)
                resolved_cli_auth_repo.put_pending_code(
                    code=auth_code,
                    payload={
                        "redirect_uri": pending["redirect_uri"],
                        "state": pending["state"],
                        "code_challenge": pending["code_challenge"],
                        "principal": principal,
                    },
                    expires_at=expires_at_code,
                )
                redirect_target = (
                    f"{pending['redirect_uri']}?code={auth_code}&state={pending['state']}"
                )
                return RedirectResponse(
                    url=redirect_target, status_code=status.HTTP_303_SEE_OTHER
                )

        if state and state.startswith("sso:"):
            pending = resolved_cli_auth_repo.pop_pending_login(login_id=state)
            redirect_target = safe_return_to(
                str(pending.get("return_to", "/")) if pending is not None else "/"
            )
            return browser_session_response(principal, redirect_target)

        # Normal browser login flow
        return browser_session_response(principal, "/portal")

    @app.post("/auth/server-logout")
    async def server_logout(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        """Revoke the current session token server-side."""
        token = None
        if authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
        if token is None:
            token = request.cookies.get(settings.session_cookie_name)

        if token:
            try:
                auth_token = identity_service.authenticate_token(token)
                jti = str(auth_token.claims.get("jti", ""))
                if jti:
                    resolved_revoked_token_repo.revoke(jti)
            except Exception:
                # Invalid token — no-op
                pass

        response = JSONResponse(content={"status": "logged out"})
        response.delete_cookie(
            key=settings.session_cookie_name,
            path="/",
            domain=settings.session_cookie_domain,
        )
        return response

    @app.get("/auth/upstream/codex/callback", include_in_schema=False, response_model=None)
    async def codex_oauth_callback(
        code: str | None = None,
        state: str | None = None,
    ) -> RedirectResponse:
        if not code or not state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both code and state are required",
            )
        pending_principal = resolved_cli_auth_repo.pop_codex_oauth_principal(state=state)
        if pending_principal is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired Codex OAuth state",
            )

        identity = resolved_codex_oauth_broker.finish(
            code=code,
            state=state,
            principal=pending_principal,
        )
        credential = credential_pool.create_credential(
            provider="openai-codex",
            auth_kind="codex_chatgpt_oauth_managed",
            account_id=identity.subject,
            scopes=identity.scopes,
            access_token=identity.access_token,
            refresh_token=identity.refresh_token,
            max_concurrency=settings.codex_credential_max_concurrency,
            expires_at=identity.expires_at,
            owner_principal_id=pending_principal.user_id,
            visibility=CredentialVisibility.PRIVATE,
            source="codex_chatgpt_oauth_managed",
            billing_model="subscription",
        )
        sync_newapi_credential(credential.id, pending_principal, shared=False)
        response = RedirectResponse(url="/portal", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            key=settings.session_cookie_name,
            value=identity_service.issue_access_token(pending_principal),
            httponly=True,
            samesite="lax",
            secure=settings.session_cookie_secure,
            max_age=settings.session_cookie_max_age_seconds,
            path="/",
            domain=settings.session_cookie_domain,
        )
        return response

    @app.get("/v1/models")
    async def list_models(
        principal: Principal = Depends(require_principal),
    ) -> dict[str, list[dict[str, object]]]:
        return {
            "data": model_catalog.list_models_for_principal(
                principal,
                credential_pool,
                routable_only=True,
            )
        }

    @app.get("/cli/models")
    async def list_cli_models(
        principal: Principal = Depends(require_cli_session),
    ) -> dict[str, list[dict[str, object]]]:
        visible_models = model_catalog.list_models_for_principal(principal, credential_pool)
        routable_models: list[dict[str, object]] = []
        for model in visible_models:
            is_routable, unavailable_reason = _credential_route_status(model, principal)
            if is_routable:
                routable_models.append({**model, "routable": True})
            elif unavailable_reason is not None:
                routable_models.append(
                    {
                        **model,
                        "routable": False,
                        "unavailable_reason": unavailable_reason,
                    }
                )
        return {"data": routable_models}

    @app.get(
        "/portal",
        response_class=HTMLResponse,
        include_in_schema=False,
        response_model=None,
    )
    async def portal() -> HTMLResponse:
        return HTMLResponse(spa_index_html)

    @app.get(
        "/portal/{path:path}",
        response_class=HTMLResponse,
        include_in_schema=False,
        response_model=None,
    )
    async def portal_catchall(path: str) -> HTMLResponse:
        del path
        return HTMLResponse(spa_index_html)

    @app.get("/install/routerctl.sh", include_in_schema=False)
    async def install_routerctl_sh() -> HTMLResponse:
        try:
            wheel_filename = resolved_distribution_service.wheel_filename()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            )
        script = bootstrap_service.build_routerctl_install_script(wheel_filename=wheel_filename)
        return HTMLResponse(content=script, media_type="text/plain")

    @app.get("/install/routerctl.ps1", include_in_schema=False)
    async def install_routerctl_ps1() -> HTMLResponse:
        try:
            wheel_filename = resolved_distribution_service.wheel_filename()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            )
        script = bootstrap_service.build_routerctl_powershell_install_script(
            wheel_filename=wheel_filename
        )
        return HTMLResponse(content=script, media_type="text/plain")

    @app.get("/install/artifacts/{filename}", include_in_schema=False)
    async def install_routerctl_wheel(filename: str) -> HTMLResponse:
        from fastapi.responses import FileResponse
        try:
            wheel_path = resolved_distribution_service.wheel_path(filename)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact not found: {filename}",
            )
        return FileResponse(
            path=str(wheel_path),
            media_type="application/zip",
            filename=filename,
        )

    @app.get("/admin/credentials")
    async def list_credentials(
        principal: Principal = Depends(require_admin),
    ) -> dict[str, list[dict[str, object]]]:
        del principal
        return {
            "data": [item.to_public_dict() for item in credential_pool.list_credentials()]
        }

    @app.post("/admin/credentials", status_code=status.HTTP_201_CREATED)
    async def create_credential(
        payload: dict[str, object],
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        credential = credential_pool.create_credential(
            provider=str(payload["provider"]),
            auth_kind=str(payload["auth_kind"]),
            account_id=str(payload["account_id"]),
            provider_alias=payload.get("provider_alias") and str(payload["provider_alias"]),
            scopes=[str(scope) for scope in payload.get("scopes", [])],
            access_token=payload.get("access_token") and str(payload["access_token"]),
            refresh_token=payload.get("refresh_token") and str(payload["refresh_token"]),
            max_concurrency=int(payload.get("max_concurrency", 1)),
            owner_principal_id=payload.get("owner_principal_id")
            and str(payload["owner_principal_id"]),
            visibility=CredentialVisibility(
                str(payload.get("visibility", CredentialVisibility.ENTERPRISE_POOL.value))
            ),
            source=payload.get("source") and str(payload["source"]),
            billing_model=payload.get("billing_model") and str(payload["billing_model"]),
            catalog_info=dict(payload["catalog_info"]) if isinstance(payload.get("catalog_info"), dict) else None,
        )
        return credential.to_public_dict()

    @app.post("/admin/credentials/{credential_id}/refresh")
    async def refresh_credential(
        credential_id: str,
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        credential = credential_pool.refresh_credential(credential_id)
        return credential.to_public_dict()

    @app.patch("/admin/upstream-credentials/{credential_id}")
    @app.patch("/admin/credentials/{credential_id}")
    async def update_admin_credential(
        credential_id: str,
        payload: dict[str, object],
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        if "max_concurrency" not in payload:
            raise HTTPException(
                status_code=422,
                detail="max_concurrency is required",
            )
        try:
            max_concurrency = int(payload["max_concurrency"])
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="max_concurrency must be an integer",
            )
        credential = credential_pool.update_max_concurrency(
            credential_id,
            max_concurrency=max_concurrency,
        )
        return credential.to_public_dict()

    @app.delete("/admin/upstream-credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
    @app.delete("/admin/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_admin_credential(
        credential_id: str,
        principal: Principal = Depends(require_admin),
    ) -> None:
        del principal
        if credential_pool.get_credential(credential_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        credential_pool.delete_credential(credential_id)

    @app.get("/admin/quotas")
    async def list_quotas(
        principal: Principal = Depends(require_admin),
    ) -> dict[str, list[dict[str, object]]]:
        del principal
        return {"data": [item.to_public_dict() for item in quota_service.list_quotas()]}

    @app.post("/admin/quotas")
    async def set_quota(
        payload: dict[str, object],
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        quota = quota_service.set_quota(
            scope_type=str(payload["scope_type"]),
            scope_id=str(payload["scope_id"]),
            limit=int(payload["limit"]),
        )
        return quota.to_public_dict()

    @app.get("/admin/usage")
    async def list_usage(
        principal: Principal = Depends(require_admin),
    ) -> dict[str, list[dict[str, object]]]:
        del principal
        return {"data": [item.to_public_dict() for item in resolved_usage_ledger.list_events()]}

    @app.get("/admin/usage/summary")
    async def usage_summary(
        period: str = "30d",
        principal: Principal = Depends(require_admin),
    ) -> dict[str, list[dict[str, object]]]:
        del principal
        now = datetime.now(UTC)
        if period == "7d":
            since: datetime | None = now - timedelta(days=7)
        elif period == "30d":
            since = now - timedelta(days=30)
        elif period == "all":
            since = None
        else:
            since = now - timedelta(days=30)
        data = resolved_usage_ledger.summarize_usage(since)
        return {"data": data}

    @app.get("/admin/upstream-credentials")
    async def list_upstream_credentials_for_admin(
        principal: Principal = Depends(require_admin),
    ) -> dict[str, list[dict[str, object]]]:
        del principal
        return {
            "data": [item.to_public_dict() for item in credential_pool.list_credentials()]
        }

    @app.post("/admin/upstream-credentials/{credential_id}/promote")
    async def promote_upstream_credential(
        credential_id: str,
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        credential = credential_pool.update_visibility(
            credential_id,
            visibility=CredentialVisibility.ENTERPRISE_POOL,
        )
        sync_newapi_credential(
            credential.id,
            sync_principal_for_credential(credential, principal),
            shared=True,
        )
        return credential.to_public_dict()

    @app.post("/admin/upstream-credentials/{credential_id}/demote")
    async def demote_upstream_credential(
        credential_id: str,
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        credential = credential_pool.update_visibility(
            credential_id,
            visibility=CredentialVisibility.PRIVATE,
        )
        sync_newapi_credential(
            credential.id,
            sync_principal_for_credential(credential, principal),
            shared=False,
        )
        return credential.to_public_dict()

    @app.post("/admin/newapi/upstream-credentials/sync")
    async def sync_upstream_credentials_to_newapi(
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        results: list[dict[str, object]] = []
        synced = 0
        unsupported = 0
        failed = 0
        for credential in credential_pool.list_credentials():
            try:
                result = newapi_sync_service.sync_credential(
                    credential,
                    principal_for_stored_credential(credential),
                    shared=credential.visibility == CredentialVisibility.ENTERPRISE_POOL,
                )
            except Exception as exc:
                failed += 1
                logging.getLogger(__name__).exception(
                    "new-api credential backfill failed for %s",
                    credential.id,
                )
                results.append(
                    {
                        "credential_id": credential.id,
                        "provider": credential.provider,
                        "action": "failed",
                        "message": str(exc),
                    }
                )
                continue

            if result.action == "unsupported":
                unsupported += 1
            elif result.enabled:
                synced += 1
            results.append(
                {
                    "credential_id": credential.id,
                    "provider": credential.provider,
                    "action": result.action,
                    "group": result.group,
                    "enabled": result.enabled,
                }
            )
        return {
            "synced": synced,
            "unsupported": unsupported,
            "failed": failed,
            "results": results,
        }

    @app.get("/admin/cli/sessions")
    async def list_cli_sessions(
        principal: Principal = Depends(require_admin),
    ) -> dict[str, list[dict[str, object]]]:
        del principal
        rows = resolved_issued_token_repo.list_active(kind="cli_session")
        return {
            "data": [
                {
                    "jti": row.jti,
                    "kind": row.kind,
                    "email": row.email,
                    "client": row.client,
                    "model": row.model,
                    "issued_at": row.issued_at.isoformat(),
                    "expires_at": row.expires_at.isoformat(),
                    "is_revoked": resolved_revoked_token_repo.is_revoked(row.jti),
                }
                for row in rows
            ]
        }

    @app.get("/admin/cli/activations")
    async def list_cli_activations(
        principal: Principal = Depends(require_admin),
    ) -> dict[str, list[dict[str, object]]]:
        del principal
        rows = resolved_issued_token_repo.list_active(kind="client_access")
        return {
            "data": [
                {
                    "jti": row.jti,
                    "kind": row.kind,
                    "email": row.email,
                    "client": row.client,
                    "model": row.model,
                    "issued_at": row.issued_at.isoformat(),
                    "expires_at": row.expires_at.isoformat(),
                    "is_revoked": resolved_revoked_token_repo.is_revoked(row.jti),
                }
                for row in rows
            ]
        }

    @app.post("/admin/cli/revoke/{jti}")
    async def revoke_cli_token(
        jti: str,
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        resolved_revoked_token_repo.revoke(jti)
        return {"status": "revoked", "jti": jti}

    # --- Admin: Custom Model Catalog ---

    @app.get("/admin/models")
    async def list_admin_models(
        principal: Principal = Depends(require_admin),
    ) -> dict[str, list[dict[str, object]]]:
        del principal
        if not session_factory:
            return {"data": []}
        from enterprise_llm_proxy.repositories.models import CustomModelRecord

        with session_factory() as session:
            rows = session.query(CustomModelRecord).order_by(CustomModelRecord.id).all()
            return {
                "data": [
                    {
                        "id": r.id,
                        "display_name": r.display_name,
                        "provider": r.provider,
                        "model_profile": r.model_profile,
                        "upstream_model": r.upstream_model,
                        "description": r.description,
                        "auth_modes": list(r.auth_modes),
                        "supported_clients": list(r.supported_clients),
                        "enabled": r.enabled,
                        "created_at": r.created_at.isoformat(),
                        "updated_at": r.updated_at.isoformat(),
                    }
                    for r in rows
                ]
            }

    @app.post("/admin/models", status_code=status.HTTP_201_CREATED)
    async def create_admin_model(
        payload: dict[str, object],
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        if not session_factory:
            raise HTTPException(status_code=503, detail="Database not configured")
        from enterprise_llm_proxy.repositories.models import CustomModelRecord

        now = datetime.now(UTC)
        record = CustomModelRecord(
            id=str(payload["id"]),
            display_name=str(payload["display_name"]),
            provider=str(payload["provider"]),
            model_profile=str(payload["model_profile"]),
            upstream_model=str(payload["upstream_model"]),
            description=str(payload.get("description", "")),
            auth_modes=[str(a) for a in payload.get("auth_modes", [])],
            supported_clients=[str(c) for c in payload.get("supported_clients", [])],
            enabled=bool(payload.get("enabled", True)),
            created_at=now,
            updated_at=now,
        )
        with session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return {
                "id": record.id,
                "display_name": record.display_name,
                "provider": record.provider,
                "model_profile": record.model_profile,
                "upstream_model": record.upstream_model,
                "description": record.description,
                "auth_modes": list(record.auth_modes),
                "supported_clients": list(record.supported_clients),
                "enabled": record.enabled,
                "created_at": record.created_at.isoformat(),
                "updated_at": record.updated_at.isoformat(),
            }

    @app.patch("/admin/models/{model_id:path}")
    async def patch_admin_model(
        model_id: str,
        payload: dict[str, object],
        principal: Principal = Depends(require_admin),
    ) -> dict[str, object]:
        del principal
        if not session_factory:
            raise HTTPException(status_code=503, detail="Database not configured")
        from enterprise_llm_proxy.repositories.models import CustomModelRecord

        with session_factory() as session:
            record = session.get(CustomModelRecord, model_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"Custom model not found: {model_id}")
            for field in (
                "display_name", "provider", "model_profile", "upstream_model", "description",
            ):
                if field in payload:
                    setattr(record, field, str(payload[field]))
            if "auth_modes" in payload:
                record.auth_modes = [str(a) for a in payload["auth_modes"]]
            if "supported_clients" in payload:
                record.supported_clients = [str(c) for c in payload["supported_clients"]]
            if "enabled" in payload:
                record.enabled = bool(payload["enabled"])
            record.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(record)
            return {
                "id": record.id,
                "display_name": record.display_name,
                "provider": record.provider,
                "model_profile": record.model_profile,
                "upstream_model": record.upstream_model,
                "description": record.description,
                "auth_modes": list(record.auth_modes),
                "supported_clients": list(record.supported_clients),
                "enabled": record.enabled,
                "created_at": record.created_at.isoformat(),
                "updated_at": record.updated_at.isoformat(),
            }

    @app.delete("/admin/models/{model_id:path}")
    async def delete_admin_model(
        model_id: str,
        principal: Principal = Depends(require_admin),
    ) -> dict[str, str]:
        del principal
        if not session_factory:
            raise HTTPException(status_code=503, detail="Database not configured")
        from enterprise_llm_proxy.repositories.models import CustomModelRecord

        with session_factory() as session:
            record = session.get(CustomModelRecord, model_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"Custom model not found: {model_id}")
            session.delete(record)
            session.commit()
            return {"status": "deleted", "id": model_id}

    @app.get("/me/upstream-credentials")
    async def list_my_upstream_credentials(
        principal: Principal = Depends(require_principal),
    ) -> dict[str, list[dict[str, object]]]:
        return {
            "data": [item.to_public_dict() for item in credential_pool.list_for_owner(principal.user_id)]
        }

    @app.post("/me/upstream-credentials/codex-oauth/start")
    async def start_codex_oauth(
        principal: Principal = Depends(require_principal),
    ) -> dict[str, str]:
        flow = resolved_codex_oauth_broker.start(principal)
        resolved_cli_auth_repo.put_codex_oauth_principal(
            state=flow.state,
            principal=principal,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
        return {
            "authorize_url": flow.authorize_url,
            "state": flow.state,
        }

    @app.post("/me/upstream-credentials/codex/import", status_code=status.HTTP_201_CREATED)
    async def import_codex_cli_credential(
        payload: dict[str, object],
        principal: Principal = Depends(require_principal),
    ) -> dict[str, object]:
        expires_at = payload.get("expires_at")
        parsed_expires_at = (
            datetime.fromisoformat(str(expires_at)) if isinstance(expires_at, str) else None
        )
        available_models = _normalize_available_models(payload.get("available_models"))
        credential = credential_pool.create_credential(
            provider="openai-codex",
            auth_kind="codex_chatgpt_oauth_imported",
            account_id=str(payload["account_id"]),
            scopes=[str(scope) for scope in payload.get("scopes", [])],
            access_token=str(payload["access_token"]),
            refresh_token=payload.get("refresh_token") and str(payload["refresh_token"]),
            max_concurrency=int(
                payload.get("max_concurrency", settings.codex_credential_max_concurrency)
            ),
            expires_at=parsed_expires_at,
            owner_principal_id=principal.user_id,
            visibility=CredentialVisibility.PRIVATE,
            source="codex_cli_import",
            billing_model="subscription",
            catalog_info=_merge_available_models(None, available_models),
        )
        sync_newapi_credential(credential.id, principal, shared=False)
        return credential.to_public_dict()

    @app.post("/me/upstream-credentials/claude-max/import", status_code=status.HTTP_201_CREATED)
    async def import_claude_max_credential(
        payload: dict[str, object],
        principal: Principal = Depends(require_principal),
    ) -> dict[str, object]:
        expires_at = payload.get("expires_at")
        parsed_expires_at = (
            datetime.fromisoformat(str(expires_at)) if isinstance(expires_at, str) else None
        )
        account_id = str(payload["account_id"])
        available_models = _normalize_available_models(payload.get("available_models"))

        # Upsert: if this owner already has a claude-max credential for this account,
        # update the tokens rather than creating a duplicate.
        existing = next(
            (
                c for c in credential_pool.list_for_owner(principal.user_id)
                if c.provider == "claude-max" and c.account_id == account_id
            ),
            None,
        )
        if existing is not None:
            from dataclasses import replace as dc_replace
            updated = dc_replace(
                existing,
                access_token=str(payload["access_token"]),
                refresh_token=payload.get("refresh_token") and str(payload["refresh_token"]),
                expires_at=parsed_expires_at,
                state=CredentialState.ACTIVE,
                cooldown_until=None,
                scopes=[str(s) for s in payload.get("scopes", [])],
                catalog_info=_merge_available_models(existing.catalog_info, available_models),
            )
            credential = credential_pool.update_credential(updated)
        else:
            credential = credential_pool.create_credential(
                provider="claude-max",
                auth_kind="oauth_subscription",
                account_id=account_id,
                scopes=[str(scope) for scope in payload.get("scopes", [])],
                access_token=str(payload["access_token"]),
                refresh_token=payload.get("refresh_token") and str(payload["refresh_token"]),
                max_concurrency=int(payload.get("max_concurrency", 1)),
                expires_at=parsed_expires_at,
                owner_principal_id=principal.user_id,
                visibility=CredentialVisibility.PRIVATE,
                source="claude_code_cli_import",
                billing_model="subscription",
                catalog_info=_merge_available_models(None, available_models),
            )
        sync_newapi_credential(credential.id, principal, shared=False)
        return credential.to_public_dict()

    @app.post("/me/upstream-credentials/{credential_id}/share")
    async def share_upstream_credential(
        credential_id: str,
        principal: Principal = Depends(require_principal),
    ) -> dict[str, object]:
        credential = credential_pool.get_credential(credential_id)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.owner_principal_id != principal.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only share your own upstream credentials",
            )
        updated = credential_pool.update_visibility(
            credential_id,
            visibility=CredentialVisibility.ENTERPRISE_POOL,
        )
        sync_newapi_credential(updated.id, principal, shared=True)
        return updated.to_public_dict()

    @app.post("/me/upstream-credentials/{credential_id}/unshare")
    async def unshare_upstream_credential(
        credential_id: str,
        principal: Principal = Depends(require_principal),
    ) -> dict[str, object]:
        credential = credential_pool.get_credential(credential_id)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.owner_principal_id != principal.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only unshare your own upstream credentials",
            )
        updated = credential_pool.update_visibility(
            credential_id,
            visibility=CredentialVisibility.PRIVATE,
        )
        sync_newapi_credential(updated.id, principal, shared=False)
        return updated.to_public_dict()

    @app.delete("/me/upstream-credentials/{credential_id}", status_code=204)
    async def delete_my_upstream_credential(
        credential_id: str,
        principal: Principal = Depends(require_principal),
    ) -> None:
        cred = credential_pool.get_credential(credential_id)
        if cred is None or cred.owner_principal_id != principal.user_id:
            raise HTTPException(status_code=404, detail="Credential not found")
        credential_pool.delete_credential(credential_id)

    @app.post("/me/upstream-credentials/{credential_id}/refresh-quota")
    async def refresh_my_credential_quota(
        credential_id: str,
        principal: Principal = Depends(require_principal),
    ) -> dict[str, object]:
        from enterprise_llm_proxy.services import credential_quota

        cred = credential_pool.get_credential(credential_id)
        if cred is None or cred.owner_principal_id != principal.user_id:
            raise HTTPException(status_code=404, detail="Credential not found")
        try:
            result = await credential_quota.fetch_quota(cred)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
        except credential_quota.QuotaFetchError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
        if "windows" in result:
            merged_quota_info = dict(cred.quota_info or {})
            merged_quota_info.update(result)
            updated = cred.replace(
                billing_model="subscription",
                quota_info=merged_quota_info,
                catalog_info=_merge_available_models(
                    cred.catalog_info,
                    _normalize_available_models(result.get("available_models")),
                ),
            )
        else:
            updated = cred.replace(billing_model="pay_per_use", billing_info=result)
        saved = credential_pool.update_credential(updated)
        return saved.to_public_dict()

    _BYOK_API_KEY_PROVIDERS = {
        "anthropic",
        "openai",
        "zhipu",
        "deepseek",
        "qwen",
        "minimax",
        "jina",
    }
    # compat providers accept a custom base_url stored as JSON in access_token
    _BYOK_COMPAT_PROVIDERS = {"anthropic_compat", "openai_compat"}

    @app.post("/me/upstream-credentials/api-key", status_code=status.HTTP_201_CREATED)
    async def add_byok_api_key(
        payload: dict[str, object],
        principal: Principal = Depends(require_principal),
    ) -> dict[str, object]:
        import json as _json
        provider = str(payload.get("provider", "")).strip().lower()
        api_key = str(payload.get("api_key", "")).strip()
        label = str(payload.get("label", "")).strip() or provider
        base_url = str(payload.get("base_url", "")).strip()
        provider_alias = normalize_provider_alias(payload.get("provider_alias"))
        all_providers = _BYOK_API_KEY_PROVIDERS | _BYOK_COMPAT_PROVIDERS
        if provider not in all_providers:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unsupported provider: {provider}. Supported: {sorted(all_providers)}",
            )
        if not api_key:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="api_key is required")
        if provider in _BYOK_COMPAT_PROVIDERS and not base_url:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="base_url is required for compat providers")
        catalog_info = None
        if provider in _BYOK_COMPAT_PROVIDERS:
            try:
                _validate_compat_alias_conflicts(
                    provider_alias=provider_alias,
                    principal=principal,
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
            try:
                discovered_models = discover_compat_models(
                    provider=provider,
                    base_url=base_url,
                    api_key=api_key,
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
            except CompatModelDiscoveryError as exc:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
            catalog_info = _merge_available_models(None, discovered_models)
        elif provider == "jina":
            from enterprise_llm_proxy.services.newapi import NATIVE_API_KEY_PROVIDER_DEFAULT_MODELS

            catalog_info = _merge_available_models(
                None,
                NATIVE_API_KEY_PROVIDER_DEFAULT_MODELS["jina"],
            )
        from enterprise_llm_proxy.domain.credentials import CredentialVisibility
        # For compat providers encode both api_key and base_url into access_token as JSON
        stored_token = _json.dumps({"api_key": api_key, "base_url": base_url}) if provider in _BYOK_COMPAT_PROVIDERS else api_key
        source = "byok_compat" if provider in _BYOK_COMPAT_PROVIDERS else "byok_api_key"
        raw_billing_model = str(payload.get("billing_model", "")).strip() or None
        if raw_billing_model and raw_billing_model not in ("subscription", "pay_per_use"):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="billing_model must be 'subscription' or 'pay_per_use'")
        cred = credential_pool.create_credential(
            provider=provider,
            auth_kind="api_key",
            account_id=label,
            provider_alias=provider_alias if provider in _BYOK_COMPAT_PROVIDERS else None,
            scopes=[],
            access_token=stored_token,
            refresh_token=None,
            max_concurrency=4,
            owner_principal_id=principal.user_id,
            visibility=CredentialVisibility.PRIVATE,
            source=source,
            billing_model=raw_billing_model,
            catalog_info=catalog_info,
        )
        return cred.to_public_dict()

    @app.get("/me/api-keys")
    async def list_my_api_keys(
        principal: Principal = Depends(require_principal),
    ) -> dict[str, object]:
        keys = api_key_service.list_for_user(principal.user_id)
        return {"data": [k.to_public_dict() for k in keys]}

    @app.delete("/me/api-keys/{key_id}", status_code=204)
    async def delete_my_api_key(
        key_id: str,
        principal: Principal = Depends(require_principal),
    ) -> None:
        deleted = api_key_service.delete_key(key_id, principal.user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="API key not found")

    @app.get("/me/preferences")
    async def get_my_preferences(principal: Principal = Depends(require_principal)) -> dict:
        prefs = resolved_preferences_repo.get(principal.user_id)
        if prefs is None:
            return {"user_id": principal.user_id, "default_model": None, "routing_config": {}}
        return prefs.to_dict()

    @app.patch("/me/preferences")
    async def patch_my_preferences(
        payload: dict[str, object],
        principal: Principal = Depends(require_principal),
    ) -> dict:
        default_model = payload.get("default_model")
        routing_config = payload.get("routing_config")
        prefs = resolved_preferences_repo.upsert(
            user_id=principal.user_id,
            default_model=str(default_model) if default_model else None,
            routing_config=dict(routing_config) if isinstance(routing_config, dict) else None,
        )
        return prefs.to_dict()

    @app.get("/me/stats")
    async def get_my_stats(
        principal: Principal = Depends(require_principal),
    ) -> dict:
        activity = resolved_usage_ledger.activity_for_user(principal.user_id, days=30)
        requests_this_month = sum(row.get("request_count", 0) for row in activity)
        tokens_this_month = sum(row.get("tokens_in", 0) + row.get("tokens_out", 0) for row in activity)
        keys = api_key_service.list_for_user(principal.user_id)
        active_api_keys = len(keys)
        return {
            "requests_this_month": requests_this_month,
            "tokens_this_month": tokens_this_month,
            "active_api_keys": active_api_keys,
        }

    @app.get("/me/usage/activity")
    async def get_my_activity(
        period: str = "7d",
        principal: Principal = Depends(require_principal),
    ) -> dict:
        days = 30
        if period.endswith("d"):
            try:
                days = int(period[:-1])
            except ValueError:
                pass
        data = resolved_usage_ledger.activity_for_user(principal.user_id, days=days)
        return {"data": data, "period": period}

    @app.get("/me/usage/activity/by-model")
    async def get_my_activity_by_model(
        days: int = 7,
        principal: Principal = Depends(require_principal),
    ) -> dict:
        data = resolved_usage_ledger.activity_by_model_for_user(principal.user_id, days=days)
        return {"data": data}

    @app.get("/me/usage/logs")
    async def get_my_logs(
        page: int = 1,
        page_size: int = 50,
        principal: Principal = Depends(require_principal),
    ) -> dict:
        offset = (page - 1) * page_size
        rows = resolved_usage_ledger.logs_for_user(principal.user_id, limit=page_size, offset=offset)
        return {"data": rows, "page": page, "page_size": page_size}

    @app.post("/developer/api-keys", status_code=status.HTTP_201_CREATED)
    async def create_developer_api_key(
        payload: dict[str, object],
        principal: Principal = Depends(require_principal),
    ) -> dict[str, object]:
        record, api_key = api_key_service.create_key(
            principal=principal,
            name=str(payload.get("name", "Developer key")),
        )
        return {
            "id": record.id,
            "name": record.name,
            "api_key": api_key,
            "key_prefix": record.key_prefix,
            "created_at": record.created_at.isoformat(),
        }

    @app.post("/developer/bootstrap/routerctl", status_code=status.HTTP_201_CREATED)
    async def bootstrap_routerctl(
        principal: Principal = Depends(require_principal),
    ) -> dict[str, object]:
        bootstrap_token = identity_service.issue_token(
            principal,
            kind="bootstrap_install",
            expires_in_seconds=settings.bootstrap_token_ttl_seconds,
        )
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=settings.bootstrap_token_ttl_seconds)
        ).isoformat()
        return {
            "bootstrap_token": bootstrap_token,
            "expires_at": expires_at,
            "install_command": bootstrap_service.build_routerctl_install_command(
                bootstrap_token=bootstrap_token,
            ),
            "windows_install_command": bootstrap_service.build_routerctl_powershell_install_command(
                bootstrap_token=bootstrap_token,
            ),
        }

    @app.post("/developer/bootstrap/claude-code", status_code=status.HTTP_201_CREATED)
    async def bootstrap_claude_code(
        payload: dict[str, object],
        principal: Principal = Depends(require_principal),
    ) -> dict[str, object]:
        record, api_key = api_key_service.create_key(
            principal=principal,
            name="Claude Code bootstrap",
        )
        model = str(payload.get("model", settings.default_claude_model))
        model_definition = model_catalog.resolve_model(model)
        if "claude_code" not in model_definition["supported_clients"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model {model} does not support Claude Code",
            )
        return {
            "id": record.id,
            "api_key": api_key,
            "script": bootstrap_service.build_claude_code_script(
                api_key=api_key,
                model=model,
            ),
            "hosts_fallback": bootstrap_service.hosts_fallback(),
        }

    @app.post("/developer/bootstrap/codex", status_code=status.HTTP_201_CREATED)
    async def bootstrap_codex(
        payload: dict[str, object],
        principal: Principal = Depends(require_principal),
    ) -> dict[str, object]:
        record, api_key = api_key_service.create_key(
            principal=principal,
            name="Codex bootstrap",
        )
        model = str(payload.get("model", settings.default_codex_model))
        model_definition = model_catalog.resolve_model(model)
        if "codex" not in model_definition["supported_clients"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model {model} does not support Codex",
            )
        return {
            "id": record.id,
            "api_key": api_key,
            "script": bootstrap_service.build_codex_script(
                api_key=api_key,
                model=model,
            ),
            "hosts_fallback": bootstrap_service.hosts_fallback(),
        }

    # --- CLI Auth endpoints ---

    @app.post("/cli/auth/start")
    async def cli_auth_start(
        payload: dict[str, object],
    ) -> dict[str, object]:
        redirect_uri = str(payload.get("redirect_uri", ""))
        state = str(payload.get("state", ""))
        code_challenge = str(payload.get("code_challenge", ""))

        from urllib.parse import urlparse as _urlparse
        parsed = _urlparse(redirect_uri)
        if parsed.hostname not in ("localhost", "127.0.0.1"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="redirect_uri must target localhost",
            )

        login_id = secrets.token_urlsafe(16)
        expires_at = datetime.now(UTC) + timedelta(minutes=15)
        resolved_cli_auth_repo.put_pending_login(
            login_id=login_id,
            payload={
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": code_challenge,
            },
            expires_at=expires_at,
        )

        base_url = settings.router_public_base_url.rstrip("/v1").rstrip("/")
        browser_url = f"{base_url}/cli/auth/browser?login_id={login_id}"
        return {
            "login_id": login_id,
            "browser_url": browser_url,
        }

    @app.get("/cli/auth/browser", include_in_schema=False, response_model=None)
    async def cli_auth_browser(login_id: str) -> RedirectResponse:
        pending = resolved_cli_auth_repo.get_pending_login(login_id=login_id)
        if pending is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Login session not found",
            )

        authorize_url = build_identity_provider_authorize_url(settings, state=f"cli:{login_id}")
        if not authorize_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SSO identity provider is not configured",
            )
        return RedirectResponse(url=authorize_url, status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/cli/auth/exchange")
    async def cli_auth_exchange(payload: dict[str, object]) -> dict[str, object]:
        code = str(payload.get("code", ""))
        code_verifier = str(payload.get("code_verifier", ""))

        pending = resolved_cli_auth_repo.pop_pending_code(code=code)
        if pending is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired CLI authorization code",
            )

        # PKCE validation: SHA256(code_verifier) base64url-encoded == code_challenge
        digest = hashlib.sha256(code_verifier.encode()).digest()
        computed_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        stored_challenge = str(pending.get("code_challenge", ""))
        if computed_challenge != stored_challenge:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PKCE validation failed",
            )

        principal = pending["principal"]
        token = identity_service.issue_token(
            principal,
            kind="cli_session",
            expires_in_seconds=settings.cli_session_ttl_seconds,
        )

        # Record issued token
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=settings.cli_session_ttl_seconds)
        try:
            claims = pyjwt.decode(token, settings.jwt_signing_secret, algorithms=["HS256"])
            jti = str(claims.get("jti", ""))
        except Exception:
            jti = ""
        if jti:
            resolved_issued_token_repo.record(
                jti=jti,
                kind="cli_session",
                principal_id=principal.user_id,
                email=principal.email,
                client=None,
                model=None,
                issued_at=now,
                expires_at=expires_at,
            )

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": expires_at.isoformat(),
            "principal": principal.to_dict() if hasattr(principal, "to_dict") else dict(principal),
        }

    @app.post("/cli/bootstrap/exchange")
    async def cli_bootstrap_exchange(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        token = authorization.removeprefix("Bearer ").strip()

        try:
            auth_token = identity_service.authenticate_token(token)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        if auth_token.kind != "bootstrap_install":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bootstrap token required",
            )

        jti = str(auth_token.claims.get("jti", ""))
        exp_ts = auth_token.claims.get("exp")
        if exp_ts is not None:
            exp_datetime = datetime.fromtimestamp(float(exp_ts), tz=UTC)
        else:
            exp_datetime = datetime.now(UTC) + timedelta(seconds=settings.bootstrap_token_ttl_seconds)

        if not resolved_cli_auth_repo.consume_jti(jti=jti, expires_at=exp_datetime):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bootstrap token has already been used",
            )

        principal = auth_token.principal
        token_out = identity_service.issue_token(
            principal,
            kind="cli_session",
            expires_in_seconds=settings.cli_session_ttl_seconds,
        )

        # Record issued token
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=settings.cli_session_ttl_seconds)
        try:
            claims = pyjwt.decode(token_out, settings.jwt_signing_secret, algorithms=["HS256"])
            new_jti = str(claims.get("jti", ""))
        except Exception:
            new_jti = ""
        if new_jti:
            resolved_issued_token_repo.record(
                jti=new_jti,
                kind="cli_session",
                principal_id=principal.user_id,
                email=principal.email,
                client=None,
                model=None,
                issued_at=now,
                expires_at=expires_at,
            )

        return {
            "access_token": token_out,
            "token_type": "bearer",
            "expires_at": expires_at.isoformat(),
            "principal": principal.to_dict(),
        }

    @app.post("/cli/activate")
    async def cli_activate(
        payload: dict[str, object],
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        token = authorization.removeprefix("Bearer ").strip()

        try:
            auth_token = identity_service.authenticate_token(token)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        if auth_token.kind != "cli_session":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CLI session required",
            )

        # Normalize client name
        client_raw = str(payload.get("client", ""))
        client_normalized = client_raw.replace("-", "_")
        if client_normalized == "codex":
            default_model = settings.default_codex_model
        else:
            default_model = settings.default_claude_model
        model = str(payload.get("model", "") or default_model)

        principal = auth_token.principal
        token_out = identity_service.issue_token(
            principal,
            kind="client_access",
            expires_in_seconds=settings.client_access_ttl_seconds,
            extra_claims={"client": client_normalized, "model": model},
        )

        # Record issued token
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=settings.client_access_ttl_seconds)
        try:
            claims = pyjwt.decode(token_out, settings.jwt_signing_secret, algorithms=["HS256"])
            new_jti = str(claims.get("jti", ""))
        except Exception:
            new_jti = ""
        if new_jti:
            resolved_issued_token_repo.record(
                jti=new_jti,
                kind="client_access",
                principal_id=principal.user_id,
                email=principal.email,
                client=client_normalized,
                model=model,
                issued_at=now,
                expires_at=expires_at,
            )

        return {
            "access_token": token_out,
            "token_type": "bearer",
            "client": client_normalized,
            "model": model,
            "router_public_base_url": settings.router_public_base_url,
        }

    def execute_inference(protocol: str, payload: dict[str, object], principal: Principal) -> JSONResponse:
        request = routing_service.build_request(
            protocol=protocol,
            payload=payload,
            principal=principal,
        )
        quota_service.ensure_capacity(principal, request.estimated_units)
        excluded_ids: set[str] = set()

        while True:
            credential, decision = routing_service.select_credential(
                request,
                excluded_ids=excluded_ids,
            )
            lease = _CredentialLease(credential.id)
            executor = executors[decision.executor]
            start = time.perf_counter()
            try:
                result = executor.execute(request, credential)
            except UpstreamRateLimitError:
                lease.mark_cooldown(seconds=300)
                excluded_ids.add(credential.id)
                continue
            except UpstreamCredentialInvalidError:
                lease.mark_disabled()
                excluded_ids.add(credential.id)
                continue
            finally:
                lease.release()

            latency_ms = int((time.perf_counter() - start) * 1000)
            resolved_usage_ledger.record(
                UsageEvent.create(
                    request_id=request.request_id,
                    principal_id=principal.user_id,
                    model_profile=request.model_profile,
                    provider=request.provider,
                    credential_id=credential.id,
                    tokens_in=result.tokens_in,
                    tokens_out=result.tokens_out,
                    latency_ms=latency_ms,
                    status="success",
                ),
                team_ids=principal.team_ids,
            )
            return JSONResponse(
                content=result.body,
                headers={"x-request-id": request.request_id},
            )

    def _prime_stream(stream: Iterator[bytes]) -> Iterator[bytes]:
        try:
            first_chunk = next(stream)
        except StopIteration:
            return iter(())

        def replay() -> Iterator[bytes]:
            yield first_chunk
            yield from stream

        return replay()

    async def _prime_async_stream(stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        try:
            first_chunk = await anext(stream)
        except StopAsyncIteration:
            async def empty() -> AsyncIterator[bytes]:
                if False:
                    yield b""

            return empty()

        async def replay() -> AsyncIterator[bytes]:
            yield first_chunk
            async for chunk in stream:
                yield chunk

        return replay()

    def execute_inference_stream(
        protocol: str,
        payload: dict[str, object],
        principal: Principal,
    ) -> JSONResponse | StreamingResponse:
        request = routing_service.build_request(
            protocol=protocol,
            payload=payload,
            principal=principal,
        )
        quota_service.ensure_capacity(principal, request.estimated_units)
        credential, decision = routing_service.select_credential(request)
        executor = executors[decision.executor]

        if credential.provider == "openai-codex" and hasattr(executor, "stream_openai_codex"):
            lease = _CredentialLease(credential.id)

            def codex_streamer():
                try:
                    yield from executor.stream_openai_codex(request, credential)
                except UpstreamRateLimitError:
                    lease.mark_cooldown(seconds=300)
                    raise
                except UpstreamCredentialInvalidError:
                    lease.mark_disabled()
                    raise
                finally:
                    lease.release()

            return StreamingResponse(
                content=_prime_stream(codex_streamer()),
                media_type="text/event-stream",
                headers={"x-request-id": request.request_id},
                background=BackgroundTask(lease.release),
            )

        if credential.provider == "claude-max" and hasattr(executor, "stream_claude_chat"):
            lease = _CredentialLease(credential.id)

            def claude_streamer():
                try:
                    yield from executor.stream_claude_chat(request, credential)
                except UpstreamRateLimitError:
                    lease.mark_cooldown(seconds=300)
                    raise
                except UpstreamCredentialInvalidError:
                    lease.mark_disabled()
                    raise
                finally:
                    lease.release()

            return StreamingResponse(
                content=claude_streamer(),
                media_type="text/event-stream",
                headers={"x-request-id": request.request_id},
                background=BackgroundTask(lease.release),
            )

        if not hasattr(executor, "execute_stream"):
            _CredentialLease(credential.id).release()
            payload_ns = {
                key: value
                for key, value in payload.items()
                if key not in {"stream", "stream_options"}
            }
            return execute_inference(protocol, payload_ns, principal)

        lease = _CredentialLease(credential.id)

        def streamer():
            try:
                yield from executor.execute_stream(request, credential)
            except UpstreamRateLimitError:
                lease.mark_cooldown(seconds=300)
                raise
            except UpstreamCredentialInvalidError:
                lease.mark_disabled()
                raise
            finally:
                lease.release()

        return StreamingResponse(
            content=_prime_stream(streamer()),
            media_type="text/event-stream",
            headers={"x-request-id": request.request_id},
            background=BackgroundTask(lease.release),
        )

    @app.post(
        "/bridge/upstreams/credentials/{credential_id}/anthropic/v1/messages",
        response_model=None,
        include_in_schema=False,
    )
    async def newapi_claude_max_anthropic_messages(
        credential_id: str,
        raw_request: Request,
        payload: dict[str, object],
        authorization: Annotated[str | None, Header()] = None,
        x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
    ) -> JSONResponse | StreamingResponse:
        require_bridge_upstream_key(authorization, x_api_key)
        credential = credential_pool.get_credential(credential_id)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.provider != "claude-max":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Credential is not a Claude Max OAuth credential",
            )
        if credential.state != CredentialState.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Credential is {credential.state.value}",
            )

        inf_request = newapi_anthropic_bridge_request(payload, credential)
        oauth_bridge = executors.get("oauth_bridge")
        if not hasattr(oauth_bridge, "execute"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OAuth bridge executor is not configured",
            )

        if not payload.get("stream"):
            try:
                result = await run_in_threadpool(
                    lambda: oauth_bridge.execute(inf_request, credential)
                )
            except UpstreamRateLimitError:
                credential_pool.mark_cooldown(credential.id, seconds=300)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Claude Max subscription rate limited",
                )
            except UpstreamCredentialInvalidError:
                credential_pool.mark_disabled(credential.id)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Claude Max OAuth credential is invalid",
                )
            return JSONResponse(
                content=result.body,
                headers={"x-request-id": inf_request.request_id},
            )

        if not hasattr(oauth_bridge, "stream_claude_max"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Claude Max streaming bridge is not configured",
            )

        _SKIP_UPSTREAM = frozenset(
            {"host", "authorization", "x-api-key", "content-length", "transfer-encoding"}
        )
        extra_headers: dict[str, str] = {
            key.lower(): value
            for key, value in raw_request.headers.items()
            if key.lower() not in _SKIP_UPSTREAM
        }
        upstream_betas = {
            beta.strip()
            for beta in extra_headers.get("anthropic-beta", "").split(",")
            if beta.strip()
        }
        upstream_betas.add("oauth-2025-04-20")
        extra_headers["anthropic-beta"] = ",".join(sorted(upstream_betas))

        async def streamer():
            try:
                async for chunk in oauth_bridge.stream_claude_max(
                    inf_request,
                    credential,
                    extra_headers,
                ):
                    yield chunk
            except UpstreamRateLimitError:
                credential_pool.mark_cooldown(credential.id, seconds=300)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Claude Max subscription rate limited",
                )
            except UpstreamCredentialInvalidError:
                credential_pool.mark_disabled(credential.id)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Claude Max OAuth credential is invalid",
                )

        primed_stream = await _prime_async_stream(streamer())
        return StreamingResponse(
            content=primed_stream,
            media_type="text/event-stream",
            headers={"x-request-id": inf_request.request_id},
        )

    async def newapi_codex_openai_bridge(
        *,
        credential_id: str,
        payload: dict[str, object],
        protocol: str,
        authorization: str | None,
        x_api_key: str | None,
    ) -> JSONResponse | StreamingResponse:
        require_bridge_upstream_key(authorization, x_api_key)
        credential = credential_pool.get_credential(credential_id)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.provider != "openai-codex":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Credential is not a Codex OAuth credential",
            )
        if credential.state != CredentialState.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Credential is {credential.state.value}",
            )

        inf_request = newapi_openai_codex_bridge_request(protocol, payload, credential)
        oauth_bridge = executors.get("oauth_bridge")
        if not hasattr(oauth_bridge, "execute"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OAuth bridge executor is not configured",
            )

        if not payload.get("stream"):
            try:
                result = await run_in_threadpool(
                    lambda: oauth_bridge.execute(inf_request, credential)
                )
            except UpstreamRateLimitError:
                credential_pool.mark_cooldown(credential.id, seconds=300)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Codex OAuth credential rate limited",
                )
            except UpstreamCredentialInvalidError:
                credential_pool.mark_disabled(credential.id)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Codex OAuth credential is invalid",
                )
            return JSONResponse(
                content=result.body,
                headers={"x-request-id": inf_request.request_id},
            )

        if not hasattr(oauth_bridge, "stream_openai_codex"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Codex streaming bridge is not configured",
            )

        def streamer() -> Iterator[bytes]:
            try:
                yield from oauth_bridge.stream_openai_codex(inf_request, credential)
            except UpstreamRateLimitError:
                credential_pool.mark_cooldown(credential.id, seconds=300)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Codex OAuth credential rate limited",
                )
            except UpstreamCredentialInvalidError:
                credential_pool.mark_disabled(credential.id)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Codex OAuth credential is invalid",
                )

        primed_stream = await run_in_threadpool(lambda: _prime_stream(streamer()))
        return StreamingResponse(
            content=primed_stream,
            media_type="text/event-stream",
            headers={"x-request-id": inf_request.request_id},
        )

    @app.post(
        "/bridge/upstreams/credentials/{credential_id}/openai/v1/chat/completions",
        response_model=None,
        include_in_schema=False,
    )
    async def newapi_codex_openai_chat_completions(
        credential_id: str,
        payload: dict[str, object],
        authorization: Annotated[str | None, Header()] = None,
        x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
    ) -> JSONResponse | StreamingResponse:
        return await newapi_codex_openai_bridge(
            credential_id=credential_id,
            payload=payload,
            protocol="openai_chat",
            authorization=authorization,
            x_api_key=x_api_key,
        )

    @app.post(
        "/bridge/upstreams/credentials/{credential_id}/openai/v1/responses",
        response_model=None,
        include_in_schema=False,
    )
    async def newapi_codex_openai_responses(
        credential_id: str,
        payload: dict[str, object],
        authorization: Annotated[str | None, Header()] = None,
        x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
    ) -> JSONResponse | StreamingResponse:
        return await newapi_codex_openai_bridge(
            credential_id=credential_id,
            payload=payload,
            protocol="openai_responses",
            authorization=authorization,
            x_api_key=x_api_key,
        )

    @app.post("/v1/chat/completions", response_model=None)
    async def chat_completions(
        payload: dict[str, object],
        principal: Principal = Depends(require_principal),
    ) -> JSONResponse | StreamingResponse:
        if payload.get("stream"):
            return await run_in_threadpool(
                execute_inference_stream, "openai_chat", payload, principal
            )
        return await run_in_threadpool(execute_inference, "openai_chat", payload, principal)

    @app.post("/v1/responses", response_model=None)
    async def responses(
        payload: dict[str, object],
        principal: Principal = Depends(require_principal),
    ) -> JSONResponse | StreamingResponse:
        if payload.get("stream"):
            return await run_in_threadpool(
                execute_inference_stream, "openai_responses", payload, principal
            )
        return await run_in_threadpool(execute_inference, "openai_responses", payload, principal)

    @app.post("/v1/messages", response_model=None)
    async def messages(
        raw_request: Request,
        payload: dict[str, object],
        principal: Principal = Depends(require_principal),
    ) -> JSONResponse | StreamingResponse:
        if not payload.get("stream"):
            return await run_in_threadpool(
                execute_inference, "anthropic_messages", payload, principal
            )

        # Streaming path — currently only supported for claude-max OAuth credentials
        inf_request = routing_service.build_request(
            protocol="anthropic_messages",
            payload=payload,
            principal=principal,
        )
        quota_service.ensure_capacity(principal, inf_request.estimated_units)
        credential, decision = routing_service.select_credential(inf_request)

        oauth_bridge = executors.get("oauth_bridge")
        if credential.provider == "openai-codex" and hasattr(oauth_bridge, "stream_openai_codex"):
            lease = _CredentialLease(credential.id)

            def codex_streamer():
                try:
                    yield from oauth_bridge.stream_openai_codex(inf_request, credential)
                except UpstreamRateLimitError:
                    lease.mark_cooldown(seconds=300)
                    raise
                except UpstreamCredentialInvalidError:
                    lease.mark_disabled()
                    raise
                finally:
                    lease.release()

            return StreamingResponse(
                content=await run_in_threadpool(lambda: _prime_stream(codex_streamer())),
                media_type="text/event-stream",
                headers={"x-request-id": inf_request.request_id},
                background=BackgroundTask(lease.release),
            )

        if not (credential.provider == "claude-max" and hasattr(oauth_bridge, "stream_claude_max")):
            # Fall back: strip stream flag, route via normal (non-streaming) path
            _CredentialLease(credential.id).release()
            payload_ns = {k: v for k, v in payload.items() if k != "stream"}
            return await run_in_threadpool(
                execute_inference, "anthropic_messages", payload_ns, principal
            )

        # Forward headers from the Claude Code client to Anthropic.
        # OAuth support at api.anthropic.com requires the originating client headers
        # (User-Agent, anthropic-client-*, etc.) to be present on the upstream request.
        _SKIP_UPSTREAM = frozenset({"host", "authorization", "x-api-key", "content-length", "transfer-encoding"})
        extra_headers: dict[str, str] = {
            k.lower(): v
            for k, v in raw_request.headers.items()
            if k.lower() not in _SKIP_UPSTREAM
        }
        # Merge Claude Code's anthropic-beta with our oauth beta (dedup).
        upstream_betas = {b.strip() for b in extra_headers.get("anthropic-beta", "").split(",") if b.strip()}
        upstream_betas.add("oauth-2025-04-20")
        extra_headers["anthropic-beta"] = ",".join(sorted(upstream_betas))

        lease = _CredentialLease(credential.id)

        async def streamer():
            try:
                async for chunk in oauth_bridge.stream_claude_max(inf_request, credential, extra_headers):
                    yield chunk
            except UpstreamRateLimitError:
                lease.mark_cooldown(seconds=300)
                raise
            except UpstreamCredentialInvalidError:
                lease.mark_disabled()
                raise
            finally:
                lease.release()

        return StreamingResponse(
            content=streamer(),
            media_type="text/event-stream",
            headers={"x-request-id": inf_request.request_id},
            background=BackgroundTask(lease.release),
        )

    return app
