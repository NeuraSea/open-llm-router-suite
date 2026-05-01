from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from enterprise_llm_proxy import cli
from enterprise_llm_proxy.services import codex_cli_import
from enterprise_llm_proxy.services.codex_cli_import import CodexCliImporter


def write_auth_file(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "last_refresh": "2026-03-19T14:00:00+00:00",
                "OPENAI_API_KEY": None,
                "tokens": {
                    "access_token": "codex-access-token",
                    "refresh_token": "codex-refresh-token",
                    "id_token": build_id_token(
                        {
                            "sub": "openai-user-1",
                            "email": "member@openai.example",
                            "exp": 1924992000,
                        }
                    ),
                    "account_id": "openai-account-1",
                },
            }
        ),
        encoding="utf-8",
    )


def write_models_cache(path: Path, slugs: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "fetched_at": "2026-04-15T02:34:57.991594Z",
                "models": [
                    {
                        "slug": slug,
                        "visibility": "list",
                    }
                    for slug in slugs
                ],
            }
        ),
        encoding="utf-8",
    )


def build_id_token(claims: dict[str, object]) -> str:
    import base64

    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).decode().rstrip("=")
    return f"{header}.{payload}."


def test_codex_importer_reads_file_store_and_uploads_private_credential(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []
    uploads: list[dict[str, object]] = []

    monkeypatch.setattr(
        CodexCliImporter,
        "_build_tls_verify",
        staticmethod(lambda **kwargs: "verify-config"),
    )
    monkeypatch.setattr(
        CodexCliImporter,
        "_should_trust_env",
        staticmethod(lambda *, router_base_url: True),
    )

    def runner(command: list[str], *, env: dict[str, str]) -> None:
        commands.append(command)
        temp_home = Path(env["CODEX_HOME"])
        config_text = (temp_home / "config.toml").read_text(encoding="utf-8")
        assert 'cli_auth_credentials_store = "file"' in config_text
        write_auth_file(temp_home / "auth.json")
        write_models_cache(temp_home / "models_cache.json", ["gpt-5.4", "gpt-5.4-mini"])

    def uploader(
        *,
        router_base_url: str,
        router_api_key: str,
        payload: dict[str, object],
        verify: object = True,
        trust_env: bool = True,
    ) -> dict[str, object]:
        uploads.append(
            {
                "router_base_url": router_base_url,
                "router_api_key": router_api_key,
                "payload": payload,
                "verify": verify,
                "trust_env": trust_env,
            }
        )
        return {"id": "cred-imported-1", "account_id": payload["account_id"]}

    importer = CodexCliImporter(
        command_runner=runner,
        router_uploader=uploader,
        temp_root=tmp_path,
    )

    result = importer.import_credential(
        router_base_url="https://router.example.com",
        router_api_key="elp_platform_key",
    )

    assert result["id"] == "cred-imported-1"
    assert commands == [["codex", "login"]]
    assert uploads == [
        {
            "router_base_url": "https://router.example.com",
            "router_api_key": "elp_platform_key",
            "payload": {
                "account_id": "openai-account-1",
                "access_token": "codex-access-token",
                "refresh_token": "codex-refresh-token",
                "scopes": ["openid", "profile", "email", "offline_access"],
                "expires_at": "2031-01-01T00:00:00+00:00",
                "subject": "openai-user-1",
                "email": "member@openai.example",
                "available_models": ["gpt-5.4", "gpt-5.4-mini"],
            },
            "verify": "verify-config",
            "trust_env": True,
        }
    ]


def test_codex_importer_falls_back_to_device_auth_and_cleans_tempdir(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    created_homes: list[Path] = []

    def runner(command: list[str], *, env: dict[str, str]) -> None:
        commands.append(command)
        temp_home = Path(env["CODEX_HOME"])
        created_homes.append(temp_home)
        if command == ["codex", "login"]:
            raise subprocess.CalledProcessError(returncode=1, cmd=command)
        write_auth_file(temp_home / "auth.json")

    importer = CodexCliImporter(
        command_runner=runner,
        router_uploader=lambda **_: {"id": "cred-imported-1"},
        temp_root=tmp_path,
    )

    result = importer.import_credential(
        router_base_url="https://router.example.com",
        router_api_key="elp_platform_key",
    )

    assert result["id"] == "cred-imported-1"
    assert commands == [["codex", "login"], ["codex", "login", "--device-auth"]]
    assert created_homes
    for home in created_homes:
        assert not home.exists()


def test_codex_importer_rejects_non_chatgpt_auth_mode(tmp_path: Path) -> None:
    def runner(command: list[str], *, env: dict[str, str]) -> None:
        del command
        temp_home = Path(env["CODEX_HOME"])
        (temp_home / "auth.json").write_text(
            json.dumps(
                {
                    "auth_mode": "api_key",
                    "OPENAI_API_KEY": "sk-test",
                    "tokens": {},
                }
            ),
            encoding="utf-8",
        )

    importer = CodexCliImporter(
        command_runner=runner,
        router_uploader=lambda **_: {"id": "unused"},
        temp_root=tmp_path,
    )

    with pytest.raises(ValueError, match="chatgpt"):
        importer.import_credential(
            router_base_url="https://router.example.com",
            router_api_key="elp_platform_key",
        )


def test_cli_codex_import_uses_env_defaults(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[dict[str, object]] = []

    class FakeImporter:
        def import_credential(
            self,
            *,
            router_base_url: str,
            router_api_key: str,
            ca_bundle: str | None = None,
            insecure: bool = False,
        ) -> dict[str, object]:
            calls.append(
                {
                    "router_base_url": router_base_url,
                    "router_api_key": router_api_key,
                    "ca_bundle": ca_bundle,
                    "insecure": insecure,
                }
            )
            return {"id": "cred-imported-1", "account_id": "openai-account-1"}

    monkeypatch.setenv("ENTERPRISE_LLM_PROXY_ROUTER_BASE_URL", "https://router.example.com/v1")
    monkeypatch.setenv("ENTERPRISE_LLM_PROXY_API_KEY", "elp_platform_key")
    monkeypatch.setenv("ENTERPRISE_LLM_PROXY_CA_BUNDLE", "/tmp/router-local-ca.crt")
    monkeypatch.setattr(cli, "CodexCliImporter", lambda codex_bin="codex": FakeImporter())
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")

    exit_code = cli.main(["codex", "import"])

    assert exit_code == 0
    assert calls == [
        {
            "router_base_url": "https://router.example.com/v1",
            "router_api_key": "elp_platform_key",
            "ca_bundle": "/tmp/router-local-ca.crt",
            "insecure": False,
        }
    ]
    assert json.loads(capsys.readouterr().out)["id"] == "cred-imported-1"


def test_codex_importer_disables_env_proxy_for_loopback_hosts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    uploads: list[dict[str, object]] = []

    def runner(command: list[str], *, env: dict[str, str]) -> None:
        del command
        write_auth_file(Path(env["CODEX_HOME"]) / "auth.json")

    def uploader(
        *,
        router_base_url: str,
        router_api_key: str,
        payload: dict[str, object],
        verify: object,
        trust_env: bool,
    ) -> dict[str, object]:
        uploads.append(
            {
                "router_base_url": router_base_url,
                "router_api_key": router_api_key,
                "payload": payload,
                "verify": verify,
                "trust_env": trust_env,
            }
        )
        return {"id": "cred-imported-1"}

    monkeypatch.setattr(
        codex_cli_import.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                0,
                0,
                0,
                "",
                ("127.0.0.1", 443),
            )
        ],
    )
    monkeypatch.setattr(
        CodexCliImporter,
        "_build_system_ssl_context",
        staticmethod(lambda router_base_url: "system-trust-context"),
    )

    importer = CodexCliImporter(
        command_runner=runner,
        router_uploader=uploader,
        temp_root=tmp_path,
    )

    result = importer.import_credential(
        router_base_url="https://router.example.com",
        router_api_key="elp_platform_key",
    )

    assert result["id"] == "cred-imported-1"
    assert uploads
    assert uploads[0]["trust_env"] is False
    assert uploads[0]["verify"] == "system-trust-context"
