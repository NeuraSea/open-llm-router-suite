from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from enterprise_llm_proxy import cli
from enterprise_llm_proxy.services import claude_code_import
from enterprise_llm_proxy.services.claude_code_import import (
    ClaudeCodeCliImporter,
    ImportedClaudeCredential,
    claude_code_oauth_headers,
    extract_claude_code_available_models,
    read_local_claude_credential,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_KEYCHAIN_PAYLOAD = {
    "claudeAiOauth": {
        "accessToken": "claude-access-token",
        "refreshToken": "claude-refresh-token",
        "expiresAt": 1924992000000,  # Unix milliseconds → 2031-01-01T00:00:00Z
        "scopes": ["openid", "profile", "email"],
        "subscriptionType": "max",
        "rateLimitTier": "high",
    }
}

_VALID_CLAUDE_JSON = {
    "oauthAccount": {
        "accountUuid": "acct-uuid-1234",
        "emailAddress": "user@example.com",
    }
}


def _make_keychain_reader(payload: dict[str, object]):
    def reader(service: str) -> dict[str, object]:
        assert service == "Claude Code-credentials"
        return payload

    return reader


# ---------------------------------------------------------------------------
# read_local_claude_credential
# ---------------------------------------------------------------------------


def test_read_local_claude_credential_parses_valid_keychain(tmp_path: Path) -> None:
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps(_VALID_CLAUDE_JSON), encoding="utf-8")

    cred = read_local_claude_credential(
        claude_json_path=claude_json,
        keychain_reader=_make_keychain_reader(_VALID_KEYCHAIN_PAYLOAD),
    )

    assert cred.account_id == "acct-uuid-1234"
    assert cred.access_token == "claude-access-token"
    assert cred.refresh_token == "claude-refresh-token"
    assert cred.scopes == ["openid", "profile", "email"]
    assert cred.subscription_type == "max"
    assert cred.email == "user@example.com"
    # 1924992000000 ms → 1924992000 s = 2031-01-01T00:00:00+00:00
    assert cred.expires_at == "2031-01-01T00:00:00+00:00"


def test_read_local_claude_credential_handles_missing_refresh_token(tmp_path: Path) -> None:
    payload = {
        "claudeAiOauth": {
            "accessToken": "claude-access-token",
            "scopes": [],
        }
    }
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps(_VALID_CLAUDE_JSON), encoding="utf-8")

    cred = read_local_claude_credential(
        claude_json_path=claude_json,
        keychain_reader=_make_keychain_reader(payload),
    )

    assert cred.refresh_token is None
    assert cred.expires_at is None
    assert cred.subscription_type is None


def test_read_local_claude_credential_missing_claude_ai_oauth_raises(tmp_path: Path) -> None:
    payload: dict[str, object] = {}
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps(_VALID_CLAUDE_JSON), encoding="utf-8")

    with pytest.raises(RuntimeError, match="PARSE_ERROR"):
        read_local_claude_credential(
            claude_json_path=claude_json,
            keychain_reader=_make_keychain_reader(payload),
        )


def test_read_local_claude_credential_missing_access_token_raises(tmp_path: Path) -> None:
    payload = {"claudeAiOauth": {"scopes": []}}
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps(_VALID_CLAUDE_JSON), encoding="utf-8")

    with pytest.raises(RuntimeError, match="PARSE_ERROR"):
        read_local_claude_credential(
            claude_json_path=claude_json,
            keychain_reader=_make_keychain_reader(payload),
        )


def test_read_local_claude_credential_missing_account_uuid_raises(tmp_path: Path) -> None:
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="ACCOUNT_NOT_FOUND"):
        read_local_claude_credential(
            claude_json_path=claude_json,
            keychain_reader=_make_keychain_reader(_VALID_KEYCHAIN_PAYLOAD),
        )


def test_read_local_claude_credential_missing_claude_json_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="ACCOUNT_NOT_FOUND"):
        read_local_claude_credential(
            claude_json_path=tmp_path / "nonexistent.json",
            keychain_reader=_make_keychain_reader(_VALID_KEYCHAIN_PAYLOAD),
        )


def test_read_local_claude_credential_handles_iso_expires_at(tmp_path: Path) -> None:
    payload = {
        "claudeAiOauth": {
            "accessToken": "tok",
            "expiresAt": "2031-01-01T00:00:00+00:00",
        }
    }
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps(_VALID_CLAUDE_JSON), encoding="utf-8")

    cred = read_local_claude_credential(
        claude_json_path=claude_json,
        keychain_reader=_make_keychain_reader(payload),
    )
    assert cred.expires_at == "2031-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# ClaudeCodeCliImporter.import_with_cli_session
# ---------------------------------------------------------------------------


def _make_valid_credential() -> ImportedClaudeCredential:
    return ImportedClaudeCredential(
        account_id="acct-uuid-1234",
        access_token="claude-access-token",
        refresh_token="claude-refresh-token",
        scopes=["openid", "profile", "email"],
        expires_at="2031-01-01T00:00:00+00:00",
        email="user@example.com",
        subscription_type="max",
    )


def test_importer_reads_credential_and_uploads_to_router() -> None:
    uploads: list[dict[str, object]] = []
    cred = _make_valid_credential()

    def reader(**_kwargs: object) -> ImportedClaudeCredential:
        return cred

    def uploader(
        *,
        router_base_url: str,
        router_bearer_token: str,
        payload: dict[str, object],
        verify: object = True,
        trust_env: bool = True,
    ) -> dict[str, object]:
        uploads.append(
            {
                "router_base_url": router_base_url,
                "router_bearer_token": router_bearer_token,
                "payload": payload,
                "verify": verify,
                "trust_env": trust_env,
            }
        )
        return {"id": "cred-1", "account_id": payload["account_id"]}

    importer = ClaudeCodeCliImporter(
        credential_reader=reader,
        router_uploader=uploader,
        available_models_fetcher=lambda access_token: (
            ["claude-sonnet-4-6", "claude-opus-4-6"] if access_token == "claude-access-token" else []
        ),
    )

    result = importer.import_with_cli_session(
        router_base_url="https://router.example.com",
        cli_session_token="session-token-xyz",
    )

    assert result["id"] == "cred-1"
    assert len(uploads) == 1
    assert uploads[0]["router_base_url"] == "https://router.example.com"
    assert uploads[0]["router_bearer_token"] == "session-token-xyz"
    assert uploads[0]["payload"]["account_id"] == "acct-uuid-1234"
    assert uploads[0]["payload"]["access_token"] == "claude-access-token"
    assert uploads[0]["payload"]["subscription_type"] == "max"
    assert uploads[0]["payload"]["available_models"] == ["claude-sonnet-4-6", "claude-opus-4-6"]


def test_importer_strips_v1_suffix_from_router_base_url() -> None:
    seen_urls: list[str] = []
    cred = _make_valid_credential()

    def uploader(*, router_base_url: str, **_kwargs: object) -> dict[str, object]:
        seen_urls.append(router_base_url)
        return {"id": "cred-1"}

    importer = ClaudeCodeCliImporter(
        credential_reader=lambda **_: cred,
        router_uploader=uploader,
    )

    importer.import_with_cli_session(
        router_base_url="https://router.example.com/v1",
        cli_session_token="session-token-xyz",
    )

    assert seen_urls == ["https://router.example.com"]


def test_importer_disables_env_proxy_for_loopback_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads: list[dict[str, object]] = []
    cred = _make_valid_credential()

    monkeypatch.setattr(
        claude_code_import.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(0, 0, 0, "", ("127.0.0.1", 443))],
    )
    monkeypatch.setattr(
        ClaudeCodeCliImporter,
        "_build_system_ssl_context",
        staticmethod(lambda router_base_url: "system-trust-context"),
    )

    def uploader(
        *,
        router_base_url: str,
        router_bearer_token: str,
        payload: dict[str, object],
        verify: object,
        trust_env: bool,
    ) -> dict[str, object]:
        uploads.append({"verify": verify, "trust_env": trust_env})
        return {"id": "cred-1"}

    importer = ClaudeCodeCliImporter(
        credential_reader=lambda **_: cred,
        router_uploader=uploader,
    )

    importer.import_with_cli_session(
        router_base_url="https://router.local",
        cli_session_token="session-token-xyz",
    )

    assert uploads[0]["trust_env"] is False
    assert uploads[0]["verify"] == "system-trust-context"


def test_extract_claude_code_available_models_returns_all_oauth_accessible_models() -> None:
    payload = {
        "data": [
            {"id": "claude-sonnet-4-6"},
            {"id": "claude-opus-4-6"},
            {"id": "claude-opus-4-5-20251101"},
            {"id": "claude-haiku-4-5-20251001"},
            {"id": "claude-sonnet-4-20250514"},
        ]
    }

    assert extract_claude_code_available_models(payload) == [
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-opus-4-5-20251101",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-20250514",
    ]


def test_claude_code_oauth_headers_include_required_beta_and_client_headers() -> None:
    headers = claude_code_oauth_headers("claude-access-token")

    assert headers["Authorization"] == "Bearer claude-access-token"
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["anthropic-beta"] == "oauth-2025-04-20"
    assert headers["anthropic-client-name"] == "claude-code"
    assert headers["anthropic-client-version"] == "2.1.108"
    assert headers["user-agent"] == "claude-code/2.1.108"


# ---------------------------------------------------------------------------
# CLI integration: routerctl claude bind
# ---------------------------------------------------------------------------


def test_cli_claude_bind_reads_session_and_calls_importer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    session_file = tmp_path / "session.json"
    session_file.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "cli-session-token",
                "expires_at": None,
                "principal": {"user_id": "u1"},
            }
        ),
        encoding="utf-8",
    )

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
            return {"id": "cred-imported-1", "account_id": "acct-uuid-1234"}

    monkeypatch.setattr(cli, "ClaudeCodeCliImporter", lambda: FakeImporter())

    exit_code = cli.main(
        ["claude", "bind", "--session-file", str(session_file)]
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
    assert "cred-imported-1" in out


def test_cli_claude_bind_reauthenticates_and_retries_when_session_token_expired(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    session_file = tmp_path / "session.json"
    session_file.write_text(
        json.dumps(
            {
                "router_base_url": "https://router.example.com",
                "access_token": "expired-cli-session-token",
                "expires_at": "2000-01-01T00:00:00+00:00",
                "principal": {"user_id": "u1"},
            }
        ),
        encoding="utf-8",
    )

    calls: list[str] = []

    class FakeImporter:
        def import_with_cli_session(
            self,
            *,
            router_base_url: str,
            cli_session_token: str,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> dict[str, object]:
            del router_base_url, ca_bundle, insecure
            calls.append(cli_session_token)
            if cli_session_token == "expired-cli-session-token":
                request = httpx.Request(
                    "POST",
                    "https://router.example.com/me/upstream-credentials/claude-max/import",
                )
                response = httpx.Response(401, request=request, json={"detail": "expired"})
                raise httpx.HTTPStatusError(
                    "401 Unauthorized: expired",
                    request=request,
                    response=response,
                )
            return {"id": "cred-imported-1", "account_id": "acct-uuid-1234"}

    def fake_browser_login(**kwargs: object) -> dict[str, object]:
        assert kwargs["router_base_url"] == "https://router.example.com"
        return {
            "access_token": "fresh-cli-session-token",
            "expires_at": "2030-01-01T00:00:00+00:00",
            "principal": {"user_id": "u1", "email": "member@example.com"},
        }

    monkeypatch.setattr(cli, "ClaudeCodeCliImporter", lambda: FakeImporter())
    monkeypatch.setattr(cli, "_run_browser_login", fake_browser_login)

    exit_code = cli.main(
        ["claude", "bind", "--session-file", str(session_file)]
    )

    assert exit_code == 0
    assert calls == ["fresh-cli-session-token"]
    stored = json.loads(session_file.read_text(encoding="utf-8"))
    assert stored["access_token"] == "fresh-cli-session-token"
    captured = capsys.readouterr()
    assert "routerctl 会话已过期" in captured.err
    assert "cred-imported-1" in captured.out


def test_cli_claude_bind_fails_without_session(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_session = tmp_path / "no-session.json"

    exit_code = cli.main(
        ["claude", "bind", "--session-file", str(missing_session)]
    )

    assert exit_code == 4
    err = capsys.readouterr().err
    assert "NOT_AUTHENTICATED" in err
