from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ENTERPRISE_LLM_PROXY_",
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    jwt_signing_secret: str = "development-signing-secret-at-least-32-bytes"
    router_public_base_url: str = "https://router.example.com/v1"
    openai_api_base_url: str = "https://api.openai.com/v1"
    openai_codex_api_base_url: str = "https://chatgpt.com/backend-api"
    openai_codex_responses_path: str = "/codex/responses"
    openai_codex_transport: str = "auto"
    default_claude_model: str = "claude-max/claude-sonnet-4-6"
    default_codex_model: str = "openai-codex/gpt-5.4"
    platform_api_key_env: str = "ENTERPRISE_LLM_PROXY_API_KEY"
    codex_client_access_env: str = "ENTERPRISE_LLM_PROXY_CODEX_ACCESS_TOKEN"
    session_cookie_name: str = "router_session"
    session_cookie_domain: str | None = None
    session_cookie_max_age_seconds: int = 8 * 60 * 60
    session_cookie_secure: bool = False
    sso_return_to_allowed_hosts: list[str] = Field(default_factory=list)
    bootstrap_token_ttl_seconds: int = 30 * 60
    cli_session_ttl_seconds: int = 8 * 60 * 60
    client_access_ttl_seconds: int = 30 * 24 * 60 * 60
    feishu_h5_sdk_url: str = "https://lf1-cdn-tos.bytegoofy.com/goofy/lark/op/h5-js-sdk-1.5.16.js"

    feishu_client_id: str | None = None
    feishu_client_secret: str | None = None
    feishu_redirect_uri: str | None = None
    feishu_app_access_token_url: str = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
    feishu_token_url: str = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
    feishu_userinfo_url: str = "https://open.feishu.cn/open-apis/authen/v1/user_info"
    admin_emails: list[str] = Field(default_factory=list)
    admin_subjects: list[str] = Field(default_factory=list)

    oidc_authorize_url: str | None = None
    oidc_token_url: str | None = None
    oidc_userinfo_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_scope: str = "openid profile email"
    oidc_login_label: str = "Company SSO"
    oidc_trust_admin_claim: bool = False

    hosts_fallback_enabled: bool = False
    hosts_fallback_domain: str | None = None
    hosts_fallback_target: str | None = None

    codex_oauth_client_id: str | None = None
    codex_oauth_client_secret: str | None = None
    codex_oauth_redirect_uri: str | None = None
    codex_oauth_authorize_url: str = "https://auth.openai.com/oauth/authorize"
    codex_oauth_token_url: str = "https://auth.openai.com/oauth/token"
    codex_oauth_userinfo_url: str = "https://auth.openai.com/userinfo"
    codex_oauth_scope: str = "openid profile email offline_access"
    codex_oauth_audience: str = "https://api.openai.com/v1"
    codex_credential_max_concurrency: int = 16

    database_url: str | None = None
    sqlalchemy_echo: bool = False
    credential_lease_ttl_seconds: int = 30 * 60

    routerctl_wheel_dir: Path = Path("/app/dist")
    lm_studio_enabled: bool = False
    lm_studio_base_url: str = "http://host.docker.internal:1234/v1"
    lm_studio_api_key: str | None = None
    lm_studio_account_id: str = "lm-studio"
    lm_studio_provider_alias: str = "lmstudio"
    lm_studio_max_concurrency: int = 1
    router_sso_issuer: str = "enterprise-llm-proxy"
    router_sso_audience: str = "new-api"
    router_sso_private_key_pem: str | None = None
    router_sso_private_key_path: Path | None = None
    router_sso_assertion_ttl_seconds: int = 60

    newapi_base_url: str | None = None
    newapi_admin_access_token: str | None = None
    newapi_admin_user_id: str | None = None
    newapi_enterprise_group: str = "default"
    newapi_sync_enabled: bool = False
    bridge_base_url_for_newapi: str | None = None
    bridge_upstream_api_key: str | None = None
