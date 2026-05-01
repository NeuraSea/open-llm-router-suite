from enterprise_llm_proxy.config import AppSettings


def test_settings_load_values_from_dotenv_local(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "ENTERPRISE_LLM_PROXY_FEISHU_CLIENT_ID=cli_env_file",
                "ENTERPRISE_LLM_PROXY_FEISHU_REDIRECT_URI=https://router.example.com/auth/oidc/callback",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ENTERPRISE_LLM_PROXY_FEISHU_CLIENT_ID", raising=False)
    monkeypatch.delenv("ENTERPRISE_LLM_PROXY_FEISHU_REDIRECT_URI", raising=False)

    settings = AppSettings()

    assert settings.feishu_client_id == "cli_env_file"
    assert settings.feishu_redirect_uri == "https://router.example.com/auth/oidc/callback"


def test_settings_use_official_feishu_defaults() -> None:
    settings = AppSettings()

    assert settings.feishu_token_url == "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
    assert settings.feishu_userinfo_url == "https://open.feishu.cn/open-apis/authen/v1/user_info"


def test_settings_read_router_sso_oidc_values(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "ENTERPRISE_LLM_PROXY_OIDC_AUTHORIZE_URL",
        "https://sso.example.com/login/oauth/authorize",
    )
    monkeypatch.setenv("ENTERPRISE_LLM_PROXY_OIDC_CLIENT_ID", "router")
    monkeypatch.setenv(
        "ENTERPRISE_LLM_PROXY_OIDC_REDIRECT_URI",
        "https://newapi.example.com/auth/oidc/callback",
    )
    monkeypatch.setenv("ENTERPRISE_LLM_PROXY_OIDC_SCOPE", "openid profile email")

    settings = AppSettings()

    assert settings.oidc_authorize_url == "https://sso.example.com/login/oauth/authorize"
    assert settings.oidc_client_id == "router"
    assert settings.oidc_redirect_uri == "https://newapi.example.com/auth/oidc/callback"
    assert settings.oidc_scope == "openid profile email"


def test_settings_read_database_url(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "ENTERPRISE_LLM_PROXY_DATABASE_URL",
        "postgresql+psycopg://router:router@localhost:5432/router",
    )

    settings = AppSettings()

    assert settings.database_url == "postgresql+psycopg://router:router@localhost:5432/router"


def test_settings_read_admin_subjects(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(
        "ENTERPRISE_LLM_PROXY_ADMIN_SUBJECTS",
        '["ou_97abfe09aaf1004b8ad5b7c37700a337","ou_admin_2"]',
    )

    settings = AppSettings()

    assert settings.admin_subjects == [
        "ou_97abfe09aaf1004b8ad5b7c37700a337",
        "ou_admin_2",
    ]


def test_settings_default_sqlalchemy_echo_is_false() -> None:
    settings = AppSettings()

    assert settings.sqlalchemy_echo is False


def test_settings_default_lm_studio_values() -> None:
    settings = AppSettings()

    assert settings.lm_studio_enabled is False
    assert settings.lm_studio_base_url == "http://host.docker.internal:1234/v1"
    assert settings.lm_studio_account_id == "lm-studio"
    assert settings.lm_studio_max_concurrency == 1


def test_settings_default_codex_credential_capacity() -> None:
    settings = AppSettings()

    assert settings.codex_credential_max_concurrency == 16


def test_settings_read_codex_credential_capacity(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ENTERPRISE_LLM_PROXY_CODEX_CREDENTIAL_MAX_CONCURRENCY", "32")

    settings = AppSettings()

    assert settings.codex_credential_max_concurrency == 32


def test_sqlalchemy_metadata_includes_persistence_tables() -> None:
    from enterprise_llm_proxy.repositories.models import Base

    assert set(Base.metadata.tables) >= {
        "platform_api_keys",
        "provider_credentials",
        "quotas",
        "usage_event_teams",
        "usage_events",
    }
