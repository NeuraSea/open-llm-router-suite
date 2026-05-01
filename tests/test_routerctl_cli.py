from __future__ import annotations

import json
from pathlib import Path

import pytest

from enterprise_llm_proxy import cli


def test_auth_bootstrap_stores_cli_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    class FakeRouterctlClient:
        def exchange_bootstrap(
            self,
            *,
            router_base_url: str,
            bootstrap_token: str,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> dict[str, object]:
            calls.append(
                {
                    "router_base_url": router_base_url,
                    "bootstrap_token": bootstrap_token,
                    "ca_bundle": ca_bundle,
                    "insecure": insecure,
                }
            )
            return {
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {
                    "user_id": "u-member",
                    "email": "member@example.com",
                    "name": "Member",
                    "team_ids": ["platform"],
                    "role": "member",
                },
            }

    session_path = tmp_path / "session.json"
    monkeypatch.setattr(cli, "RouterctlApiClient", lambda: FakeRouterctlClient())

    exit_code = cli.main(
        [
            "auth",
            "bootstrap",
            "--router-base-url",
            "https://router.example.com",
            "--bootstrap-token",
            "bootstrap-token",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 0
    assert calls == [
        {
            "router_base_url": "https://router.example.com",
            "bootstrap_token": "bootstrap-token",
            "ca_bundle": None,
            "insecure": False,
        }
    ]
    stored = json.loads(session_path.read_text(encoding="utf-8"))
    assert stored["access_token"] == "cli-session-token"
    assert stored["principal"]["email"] == "member@example.com"
    captured = capsys.readouterr()
    assert "routerctl 已登录" in captured.err
    assert json.loads(captured.out)["access_token"] == "cli-session-token"


def test_activate_claude_code_writes_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeRouterctlClient:
        def activate_client(
            self,
            *,
            router_base_url: str,
            cli_session_token: str,
            client: str,
            model: str,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> dict[str, object]:
            assert router_base_url == "https://router.example.com"
            assert cli_session_token == "cli-session-token"
            assert client == "claude-code"
            assert model == "openai-codex/gpt-5-codex"
            assert ca_bundle is None
            assert insecure is False
            return {
                "access_token": "client-access-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "client": "claude_code",
                "model": "openai-codex/gpt-5-codex",
                "router_public_base_url": "https://router.example.com/v1",
            }

    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {
                    "user_id": "u-member",
                    "email": "member@example.com",
                    "name": "Member",
                    "team_ids": ["platform"],
                    "role": "member",
                },
            }
        ),
        encoding="utf-8",
    )
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr(cli, "RouterctlApiClient", lambda: FakeRouterctlClient())
    monkeypatch.setattr(cli, "_is_loopback_router_host", lambda router_base_url: False)
    monkeypatch.setattr(cli, "_export_local_ca_certificate", lambda path: False)

    exit_code = cli.main(
        [
            "activate",
            "claude-code",
            "--model",
            "openai-codex/gpt-5-codex",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 0
    env_text = (home_dir / ".enterprise-llm-proxy" / "claude-code.env").read_text(encoding="utf-8")
    assert 'export ANTHROPIC_BASE_URL="https://router.example.com"' in env_text
    assert 'export ANTHROPIC_AUTH_TOKEN="client-access-token"' in env_text
    assert "unset ANTHROPIC_API_KEY" in env_text
    assert "export ANTHROPIC_API_KEY=" not in env_text
    assert 'export ANTHROPIC_MODEL="openai-codex/gpt-5-codex"' in env_text
    assert 'export ANTHROPIC_CUSTOM_MODEL_OPTION="openai-codex/gpt-5-codex"' in env_text


def test_claude_launch_is_delegated_to_cc_switch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeRouterctlClient:
        def activate_client(self, **kwargs: object) -> dict[str, object]:  # pragma: no cover - must not be called
            raise AssertionError("routerctl claude must not mint launch tokens")

    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "***",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {"user_id": "u-member", "email": "member@example.com"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "RouterctlApiClient", lambda: FakeRouterctlClient())
    monkeypatch.setattr(
        cli.os,
        "execvpe",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not exec")),
    )

    exit_code = cli.main(["claude", "--session-file", str(session_path), "--resume", "abc"])

    assert exit_code == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "cc-switch" in err
    assert "routerctl claude bind" in err


def test_routerctl_claude_model_option_no_longer_launches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeRouterctlClient:
        def activate_client(self, **kwargs: object) -> dict[str, object]:  # pragma: no cover - must not be called
            raise AssertionError("routerctl claude must not mint launch tokens")

    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "***",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {
                    "user_id": "u-member",
                    "email": "member@example.com",
                    "name": "Member",
                    "team_ids": ["platform"],
                    "role": "member",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "RouterctlApiClient", lambda: FakeRouterctlClient())
    monkeypatch.setattr(
        cli.os,
        "execvpe",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not exec")),
    )

    exit_code = cli.main(["claude", "--model", "zhipu/glm-5", "--session-file", str(session_path)])

    assert exit_code == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "cc-switch" in err
    assert "zhipu/glm-5" not in err


def test_claude_bind_with_share_keeps_routerctl_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    class FakeImporter:
        def import_with_cli_session(
            self,
            *,
            router_base_url: str,
            cli_session_token: str,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> dict[str, object]:
            calls.append(
                {
                    "action": "import",
                    "router_base_url": router_base_url,
                    "cli_session_token": cli_session_token,
                    "ca_bundle": ca_bundle,
                    "insecure": insecure,
                }
            )
            return {
                "id": "cred-claude-1",
                "provider": "claude-max",
                "account_id": "claude-account-1",
                "state": "active",
                "visibility": "private",
                "expires_at": "2030-01-01T00:00:00+00:00",
            }

    class FakeRouterctlClient:
        def share_upstream_credential(
            self,
            *,
            router_base_url: str,
            cli_session_token: str,
            credential_id: str,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> dict[str, object]:
            calls.append(
                {
                    "action": "share",
                    "router_base_url": router_base_url,
                    "cli_session_token": cli_session_token,
                    "credential_id": credential_id,
                    "ca_bundle": ca_bundle,
                    "insecure": insecure,
                }
            )
            return {
                "id": credential_id,
                "provider": "claude-max",
                "account_id": "claude-account-1",
                "state": "active",
                "visibility": "shared",
                "expires_at": "2030-01-01T00:00:00+00:00",
            }

    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {"user_id": "u-member", "email": "member@example.com"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "ClaudeCodeCliImporter", lambda: FakeImporter())
    monkeypatch.setattr(cli, "RouterctlApiClient", lambda: FakeRouterctlClient())

    exit_code = cli.main(
        [
            "claude",
            "--session-file",
            str(session_path),
            "--ca-bundle",
            "/tmp/router-ca.pem",
            "bind",
            "--share",
        ]
    )

    assert exit_code == 0
    assert calls == [
        {
            "action": "import",
            "router_base_url": "https://router.example.com",
            "cli_session_token": "cli-session-token",
            "ca_bundle": "/tmp/router-ca.pem",
            "insecure": False,
        },
        {
            "action": "share",
            "router_base_url": "https://router.example.com",
            "cli_session_token": "cli-session-token",
            "credential_id": "cred-claude-1",
            "ca_bundle": "/tmp/router-ca.pem",
            "insecure": False,
        },
    ]
    out = capsys.readouterr().out
    assert "Claude Max credential bound" in out
    assert "cred-claude-1" in out
    assert "shared" in out


def test_bind_codex_uses_cli_session_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    class FakeImporter:
        def import_with_cli_session(
            self,
            *,
            router_base_url: str,
            cli_session_token: str,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> dict[str, object]:
            calls.append(
                {
                    "router_base_url": router_base_url,
                    "cli_session_token": cli_session_token,
                    "ca_bundle": ca_bundle,
                    "insecure": insecure,
                }
            )
            return {
                "id": "cred-imported-1",
                "provider": "openai-codex",
                "account_id": "openai-account-1",
                "state": "active",
                "visibility": "private",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "quota_info": {
                    "available_models": ["gpt-5.4", "gpt-5.4-mini"],
                },
            }

    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {
                    "user_id": "u-member",
                    "email": "member@example.com",
                    "name": "Member",
                    "team_ids": ["platform"],
                    "role": "member",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "CodexCliImporter", lambda codex_bin="codex": FakeImporter())
    # Patch shutil.which to make codex appear available
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    exit_code = cli.main(
        [
            "codex",
            "bind",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 0
    assert calls == [
        {
            "router_base_url": "https://router.example.com",
            "cli_session_token": "cli-session-token",
            "ca_bundle": None,
            "insecure": False,
        }
    ]
    out = capsys.readouterr().out
    assert "Codex credential bound" in out
    assert "cred-imported-1" in out
    assert "openai-account-1" in out
    assert "gpt-5.4" in out
    assert "routerctl codex" in out


def test_activate_codex_writes_targeted_no_proxy_for_loopback_router(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeRouterctlClient:
        def activate_client(
            self,
            *,
            router_base_url: str,
            cli_session_token: str,
            client: str,
            model: str,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> dict[str, object]:
            assert router_base_url == "https://router.example.com"
            assert cli_session_token == "cli-session-token"
            assert client == "codex"
            assert model == "openai-codex/gpt-5-codex"
            assert ca_bundle is None
            assert insecure is False
            return {
                "access_token": "client-access-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "client": "codex",
                "model": "openai-codex/gpt-5-codex",
                "router_public_base_url": "https://router.example.com/v1",
            }

    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {
                    "user_id": "u-member",
                    "email": "member@example.com",
                    "name": "Member",
                    "team_ids": ["platform"],
                    "role": "member",
                },
            }
        ),
        encoding="utf-8",
    )
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr(cli, "RouterctlApiClient", lambda: FakeRouterctlClient())
    monkeypatch.setattr(cli, "_is_loopback_router_host", lambda router_base_url: True)
    monkeypatch.setattr(cli, "_export_local_ca_certificate", lambda path: False)

    exit_code = cli.main(
        [
            "activate",
            "codex",
            "--model",
            "openai-codex/gpt-5-codex",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 0
    env_text = (home_dir / ".enterprise-llm-proxy" / "codex.env").read_text(encoding="utf-8")
    assert 'export ENTERPRISE_LLM_PROXY_CODEX_ACCESS_TOKEN="client-access-token"' in env_text
    assert 'export NO_PROXY="router.example.com,localhost,127.0.0.1"' in env_text
    assert 'export no_proxy="$NO_PROXY"' in env_text


def test_routerctl_auth_status_shows_session_when_logged_in(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_path = tmp_path / "session.json"
    session_data = {
        "router_base_url": "https://router.example.com",
        "access_token": "cli-session-token",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "principal": {
            "user_id": "u-member",
            "email": "member@example.com",
            "name": "Member",
            "team_ids": ["platform"],
            "role": "member",
        },
    }
    session_path.write_text(json.dumps(session_data), encoding="utf-8")

    exit_code = cli.main(
        [
            "auth",
            "status",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["access_token"] == "cli-session-token"
    assert parsed["principal"]["email"] == "member@example.com"
    assert parsed["router_base_url"] == "https://router.example.com"


def test_routerctl_auth_status_shows_not_logged_in_when_no_session(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_path = tmp_path / "no-such-session.json"

    exit_code = cli.main(
        [
            "auth",
            "status",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 4
    err = capsys.readouterr().err
    assert "NOT_AUTHENTICATED" in err


def test_routerctl_auth_logout_removes_session(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {"user_id": "u-member", "email": "member@example.com"},
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "auth",
            "logout",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 0
    assert not session_path.exists()
    captured = capsys.readouterr()
    assert "退出登录" in captured.err
    assert json.loads(captured.out)["ok"] is True


def test_bind_codex_fails_when_codex_not_in_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {"user_id": "u-member", "email": "member@example.com"},
            }
        ),
        encoding="utf-8",
    )

    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)

    exit_code = cli.main(
        [
            "codex",
            "bind",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 3
    err = capsys.readouterr().err
    assert "BINARY_NOT_FOUND" in err


def test_codex_import_fails_when_codex_not_in_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)

    exit_code = cli.main(
        [
            "codex",
            "import",
            "--router-base-url",
            "https://router.example.com",
            "--router-api-key",
            "test-api-key",
        ]
    )

    assert exit_code == 3
    err = capsys.readouterr().err
    assert "BINARY_NOT_FOUND" in err


def test_logout_calls_server_logout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When logged in and logout runs, api_client.server_logout() is called with correct args."""
    calls: list[dict[str, object]] = []

    class FakeRouterctlClient:
        def server_logout(self, *, router_base_url: str, token: str) -> None:
            calls.append({"router_base_url": router_base_url, "token": token})

    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {"user_id": "u-member", "email": "member@example.com"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "RouterctlApiClient", lambda: FakeRouterctlClient())

    exit_code = cli.main(
        [
            "auth",
            "logout",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 0
    assert not session_path.exists()
    assert "退出登录" in capsys.readouterr().err
    assert calls == [
        {
            "router_base_url": "https://router.example.com",
            "token": "cli-session-token",
        }
    ]


def test_logout_still_clears_local_if_server_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Even when server_logout raises, local session file is still cleared."""

    class FakeRouterctlClientRaises:
        def server_logout(self, *, router_base_url: str, token: str) -> None:
            raise RuntimeError("server unreachable")

    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {"user_id": "u-member", "email": "member@example.com"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "RouterctlApiClient", lambda: FakeRouterctlClientRaises())

    exit_code = cli.main(
        [
            "auth",
            "logout",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 0
    assert not session_path.exists()
    assert "退出登录" in capsys.readouterr().err


def test_models_list_prints_available_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeRouterctlClient:
        def list_cli_models(
            self,
            *,
            router_base_url: str,
            cli_session_token: str,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> list[dict[str, object]]:
            assert router_base_url == "https://router.example.com"
            assert cli_session_token == "cli-session-token"
            return [
                {
                    "id": "zai-org/glm-4.7-flash",
                    "display_name": "GLM 4.7 Flash",
                    "provider": "openai_compat",
                    "supported_clients": ["codex"],
                    "supported_protocols": ["openai_chat", "openai_responses"],
                    "source": "compat",
                },
                {
                    "id": "claude-max/claude-sonnet-4-6",
                    "display_name": "Claude Sonnet 4.6",
                    "provider": "claude-max",
                    "supported_clients": ["claude_code", "codex"],
                    "supported_protocols": ["anthropic_messages", "openai_chat", "openai_responses"],
                    "source": "catalog",
                    "routable": False,
                    "unavailable_reason": "All 1 available claude-max upstream credentials are busy / leases saturated",
                },
            ]

    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {"user_id": "u-member", "email": "member@example.com"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "RouterctlApiClient", lambda: FakeRouterctlClient())

    exit_code = cli.main(
        [
            "models",
            "list",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "zai-org/glm-4.7-flash" in out
    assert "GLM 4.7 Flash" in out
    assert "claude-max/claude-sonnet-4-6" in out
    assert "unavailable" in out
    assert "leases saturated" in out


def test_models_config_only_saves_selected_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, str]] = []

    class FakeRouterctlClient:
        def list_cli_models(
            self,
            *,
            router_base_url: str,
            cli_session_token: str,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> list[dict[str, object]]:
            return [
                {
                    "id": "zai-org/glm-4.7-flash",
                    "display_name": "GLM 4.7 Flash",
                    "provider": "openai_compat",
                    "supported_clients": ["codex"],
                    "supported_protocols": ["openai_chat", "openai_responses"],
                    "source": "compat",
                }
            ]

        def get_preferences(
            self,
            *,
            router_base_url: str,
            cli_session_token: str,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> dict[str, object]:
            return {"user_id": "u-member", "default_model": None, "routing_config": {}}

        def patch_preferences(
            self,
            *,
            router_base_url: str,
            cli_session_token: str,
            default_model: str | None = None,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> dict[str, object]:
            calls.append(("save", default_model or ""))
            return {"user_id": "u-member", "default_model": default_model, "routing_config": {}}


    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {"user_id": "u-member", "email": "member@example.com"},
            }
        ),
        encoding="utf-8",
    )

    answers = iter(["1", "1"])
    monkeypatch.setattr(cli, "RouterctlApiClient", lambda: FakeRouterctlClient())
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    exit_code = cli.main(
        [
            "models",
            "config",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 0
    assert calls == [
        ("save", "zai-org/glm-4.7-flash"),
    ]
    err = capsys.readouterr().err
    assert "默认模型已保存" in err


def test_ssh_env_prints_url_instead_of_opening_browser(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With SSH_TTY set and open failing, URL is printed to stdout."""
    import subprocess
    import webbrowser

    browser_calls: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url: browser_calls.append(url) or True)
    monkeypatch.setenv("SSH_TTY", "/dev/pts/0")
    monkeypatch.delenv("DISPLAY", raising=False)
    # Simulate `open` command failing (e.g. headless CI)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: type("R", (), {"returncode": 1})())

    test_url = "https://router.example.com/auth/authorize?foo=bar"
    cli._open_browser_or_print(test_url)

    assert browser_calls == [], "webbrowser.open should NOT be called in SSH environment"
    out = capsys.readouterr().out
    assert test_url in out


def test_normal_env_opens_browser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """On macOS, subprocess `open` is called with the authorization URL."""
    import subprocess

    open_calls: list[str] = []

    def fake_run(cmd: list[str], **kw: object) -> object:
        if cmd[0] == "open":
            open_calls.append(cmd[1])
            return type("R", (), {"returncode": 0})()
        return type("R", (), {"returncode": 1})()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)

    test_url = "https://router.example.com/auth/authorize?foo=bar"
    cli._open_browser_or_print(test_url)

    assert open_calls == [test_url], "`open` should be called on macOS"


def test_activate_codex_merges_existing_codex_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """_write_codex_activation merges into existing config.toml without clobbering other sections."""

    class FakeRouterctlClient:
        def activate_client(self, **kwargs: object) -> dict[str, object]:
            return {
                "access_token": "client-access-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "client": "codex",
                "model": "openai-codex/gpt-5-codex",
                "router_public_base_url": "https://router.example.com/v1",
            }

    session_path = tmp_path / "session.json"
    session_path.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "principal": {"user_id": "u-member", "email": "member@example.com"},
            }
        ),
        encoding="utf-8",
    )
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    # Pre-create a config.toml with an existing provider
    codex_dir = home_dir / ".codex"
    codex_dir.mkdir(parents=True)
    existing_config = (
        "[model_providers.other_provider]\n"
        'name = "Other Provider"\n'
        'base_url = "https://other.example.com"\n'
    )
    (codex_dir / "config.toml").write_text(existing_config, encoding="utf-8")

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr(cli, "RouterctlApiClient", lambda: FakeRouterctlClient())
    monkeypatch.setattr(cli, "_is_loopback_router_host", lambda router_base_url: False)

    exit_code = cli.main(
        [
            "activate",
            "codex",
            "--model",
            "openai-codex/gpt-5-codex",
            "--session-file",
            str(session_path),
        ]
    )

    assert exit_code == 0
    config_text = (codex_dir / "config.toml").read_text(encoding="utf-8")
    # Both the old provider and the new one should be present
    assert "other_provider" in config_text
    assert "enterprise_router" in config_text


def test_write_codex_activation_preserves_deep_nested_toml_tables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home_dir = tmp_path / "home"
    codex_dir = home_dir / ".codex"
    codex_dir.mkdir(parents=True)
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'notify = ["node", "/tmp/hook.js"]',
                "",
                '[projects."/tmp/app"]',
                'trust_level = "trusted"',
                "",
                '[projects."/tmp/app".model_aliases]',
                'gpt-5 = {"3-codex" = "gpt-5.4"}',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_is_loopback_router_host", lambda router_base_url: False)

    cli._write_codex_activation(
        home_dir=home_dir,
        router_public_base_url="https://router.example.com/v1",
        access_token="client-access-token",
        model="openai-codex/gpt-5.4",
    )

    config_text = config_path.read_text(encoding="utf-8")
    assert "{'" not in config_text
    if cli.sys.version_info >= (3, 11):
        import tomllib

        parsed = tomllib.loads(config_text)
        assert (
            parsed["projects"]["/tmp/app"]["model_aliases"]["gpt-5"]["3-codex"]
            == "gpt-5.4"
        )
        assert parsed["profiles"]["enterprise_router"]["model"] == "openai-codex/gpt-5.4"
