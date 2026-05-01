from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from enterprise_llm_proxy.services.claude_code_import import ClaudeCodeCliImporter
from enterprise_llm_proxy.services.codex_cli_import import CodexCliImporter
from enterprise_llm_proxy.services.routerctl_client import (
    RouterctlApiClient,
    RouterctlSession,
    RouterctlSessionStore,
    find_caddy_local_ca_cert,
    is_loopback_host,
)


CODEX_ACCESS_ENV = "ENTERPRISE_LLM_PROXY_CODEX_ACCESS_TOKEN"
AUTO_LOGIN_TIMEOUT_SECONDS = 300

# Exit codes (stable contract for agent callers)
EXIT_OK = 0
EXIT_ERROR = 1       # general / unexpected error
EXIT_PARAM = 2       # bad parameters
EXIT_NOT_FOUND = 3   # resource not found (e.g. binary missing)
EXIT_AUTH = 4        # not logged in / permission denied


def _tty_color(code: str) -> str:
    """Return ANSI escape code only when stdout is a real terminal."""
    return code if sys.stdout.isatty() else ""


_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_DIM = "\033[2m"


def _format_bind_expiry(expires_raw: object) -> str:
    if not expires_raw:
        return "—"
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(str(expires_raw))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return str(expires_raw)


def _extract_available_models(result: dict[str, object]) -> list[str]:
    catalog_info = result.get("catalog_info")
    raw_models = catalog_info.get("available_models") if isinstance(catalog_info, dict) else None
    if not isinstance(raw_models, list):
        quota_info = result.get("quota_info")
        raw_models = quota_info.get("available_models") if isinstance(quota_info, dict) else None
    if not isinstance(raw_models, list):
        return []
    discovered: list[str] = []
    seen: set[str] = set()
    for raw_model in raw_models:
        model_id = str(raw_model).strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        discovered.append(model_id)
    return discovered


def _print_bind_result(
    *,
    heading: str,
    launch_command: str,
    result: dict[str, object],
) -> None:
    bold = _tty_color(_BOLD)
    green = _tty_color(_GREEN)
    cyan = _tty_color(_CYAN)
    dim = _tty_color(_DIM)
    reset = _tty_color(_RESET)

    expires_str = _format_bind_expiry(result.get("expires_at"))
    scopes = [str(scope) for scope in result.get("scopes", []) if str(scope).strip()]
    available_models = _extract_available_models(result)
    visibility = result.get("visibility", "private")
    state = result.get("state", "active")

    print(f"\n{green}{bold}✓ {heading}{reset}\n")
    col = 14

    def row(label: str, value: str) -> None:
        print(f"  {dim}{label:<{col}}{reset}{value}")

    row("ID", str(result.get("id", "")))
    row("Account", str(result.get("account_id", "")))
    row("State", state)
    row("Expires", expires_str)
    row("Visibility", visibility)

    if scopes:
        first_line = True
        for scope in scopes:
            if first_line:
                row("Scopes", f"{cyan}{scope}{reset}")
                first_line = False
            else:
                print(f"  {' ' * col}{cyan}{scope}{reset}")

    if available_models:
        preview = ", ".join(available_models[:4])
        suffix = f" (+{len(available_models) - 4} more)" if len(available_models) > 4 else ""
        row("Models", f"{len(available_models)} discovered")
        print(f"  {' ' * col}{preview}{suffix}")

    print(f"\n{dim}Run{reset} {bold}{launch_command}{reset} {dim}to start using this credential.{reset}\n")


def _print_claude_bind_result(result: dict) -> None:  # type: ignore[type-arg]
    _print_bind_result(
        heading="Claude Max credential bound",
        launch_command="routerctl claude",
        result=result,
    )


def _print_codex_bind_result(result: dict) -> None:  # type: ignore[type-arg]
    _print_bind_result(
        heading="Codex credential bound",
        launch_command="routerctl codex",
        result=result,
    )


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _session_store(path_value: str | None) -> RouterctlSessionStore:
    return RouterctlSessionStore(Path(path_value).expanduser() if path_value else None)


def _load_session(store: RouterctlSessionStore) -> RouterctlSession | None:
    return store.load()


def _session_is_expired(session: RouterctlSession, *, skew_seconds: int = 60) -> bool:
    if not session.expires_at:
        return False
    try:
        expires_at = datetime.fromisoformat(session.expires_at)
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return (expires_at - now).total_seconds() <= skew_seconds


def _login_and_store_session(
    *,
    api_client: RouterctlApiClient,
    store: RouterctlSessionStore,
    router_base_url: str,
    ca_bundle: str | None,
    insecure: bool,
    timeout_seconds: int = AUTO_LOGIN_TIMEOUT_SECONDS,
) -> RouterctlSession:
    payload = _run_browser_login(
        api_client=api_client,
        router_base_url=router_base_url,
        ca_bundle=ca_bundle,
        insecure=insecure,
        timeout_seconds=timeout_seconds,
    )
    session = RouterctlSession(
        router_base_url=router_base_url.rstrip("/"),
        access_token=str(payload["access_token"]),
        expires_at=payload.get("expires_at") and str(payload["expires_at"]),
        principal=dict(payload["principal"]),
    )
    store.save(session)
    print(f"routerctl 已重新登录：{session.principal.get('email', 'unknown')}", file=sys.stderr)
    return session


def _ensure_fresh_session(
    *,
    store: RouterctlSessionStore,
    api_client: RouterctlApiClient,
    ca_bundle: str | None,
    insecure: bool,
) -> RouterctlSession:
    session = _require_session(store)
    if not _session_is_expired(session):
        return session
    print("routerctl 会话已过期，正在重新登录...", file=sys.stderr)
    return _login_and_store_session(
        api_client=api_client,
        store=store,
        router_base_url=session.router_base_url,
        ca_bundle=ca_bundle,
        insecure=insecure,
    )


def _is_auth_status_error(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}


def _retry_once_after_reauth(
    *,
    store: RouterctlSessionStore,
    api_client: RouterctlApiClient,
    session: RouterctlSession,
    ca_bundle: str | None,
    insecure: bool,
    action,
):  # type: ignore[no-untyped-def]
    try:
        return action(session)
    except Exception as exc:
        if not _is_auth_status_error(exc):
            raise
        print("routerctl 会话已过期或被服务器拒绝，正在重新登录...", file=sys.stderr)
        fresh_session = _login_and_store_session(
            api_client=api_client,
            store=store,
            router_base_url=session.router_base_url,
            ca_bundle=ca_bundle,
            insecure=insecure,
        )
        return action(fresh_session)


def _require_session(store: RouterctlSessionStore) -> RouterctlSession:
    session = _load_session(store)
    if session is None:
        raise RuntimeError(
            "NOT_AUTHENTICATED: 未找到登录会话。"
            " 修复: routerctl auth login --router-base-url <ROUTER_BASE_URL>"
            " (可重试)"
        )
    return session


def _print_not_authenticated() -> None:
    print(
        "NOT_AUTHENTICATED: 未找到登录会话。"
        " 修复: routerctl auth login --router-base-url <ROUTER_BASE_URL>"
        " (可重试)",
        file=sys.stderr,
    )


def _is_loopback_router_host(router_base_url: str) -> bool:
    hostname = urlparse(router_base_url).hostname
    if not hostname:
        return False
    return is_loopback_host(hostname)


def _is_native_claude_model(model: str) -> bool:
    return model.startswith("claude-")


def _apply_claude_model_env(env: dict[str, str], model: str) -> None:
    if not model:
        return
    env["ANTHROPIC_MODEL"] = model
    if _is_native_claude_model(model):
        env.pop("ANTHROPIC_CUSTOM_MODEL_OPTION", None)
        env.pop("ANTHROPIC_CUSTOM_MODEL_OPTION_NAME", None)
        env.pop("ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION", None)
        return
    env["ANTHROPIC_CUSTOM_MODEL_OPTION"] = model


def _claude_code_base_url(router_public_base_url: str) -> str:
    normalized = router_public_base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[:-3]
    return normalized


def _export_local_ca_certificate(path: Path) -> bool:
    pem = find_caddy_local_ca_cert()
    if not pem:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pem, encoding="utf-8")
    return True


def _write_toml_section(f: object, data: dict, prefix: str = "") -> None:  # type: ignore[type-arg]
    """Write simple TOML: handles string values and nested sections."""
    import io
    writer = f  # type: ignore[assignment]
    simple_keys = {k: v for k, v in data.items() if not isinstance(v, dict)}
    nested_keys = {k: v for k, v in data.items() if isinstance(v, dict)}
    for key, value in simple_keys.items():
        if isinstance(value, str):
            writer.write(f'{key} = "{value}"\n')
    for key, value in nested_keys.items():
        section_name = f"{prefix}{key}" if prefix else key
        writer.write(f"\n[{section_name}]\n")
        for k, v in value.items():
            if isinstance(v, str):
                writer.write(f'{k} = "{v}"\n')


def _write_codex_activation(
    *,
    home_dir: Path,
    router_public_base_url: str,
    access_token: str,
    model: str,
) -> tuple[Path, Path]:
    env_dir = home_dir / ".enterprise-llm-proxy"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_file = env_dir / "codex.env"
    lines = [f'export {CODEX_ACCESS_ENV}="{access_token}"']
    if _is_loopback_router_host(router_public_base_url):
        router_host = urlparse(router_public_base_url).hostname or "localhost"
        lines.append(f'export NO_PROXY="{router_host},localhost,127.0.0.1"')
        lines.append('export no_proxy="$NO_PROXY"')
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config_dir = home_dir / ".codex"
    config_path = config_dir / "config.toml"

    # Read existing config if it exists
    existing: dict = {}  # type: ignore[type-arg]
    if config_path.exists():
        try:
            if sys.version_info >= (3, 11):
                import tomllib
                with open(config_path, "rb") as fh:
                    existing = tomllib.load(fh)
            else:
                try:
                    import tomli  # type: ignore[import]
                    with open(config_path, "rb") as fh:
                        existing = tomli.load(fh)
                except ImportError:
                    existing = {}
        except Exception:
            existing = {}

    # Merge our provider into existing providers section
    providers = existing.get("model_providers", {})
    providers["enterprise_router"] = {
        "name": "Enterprise Router",
        "base_url": router_public_base_url,
        "env_key": CODEX_ACCESS_ENV,
        "wire_api": "responses",
    }
    existing["model_providers"] = providers

    profiles = existing.get("profiles", {})
    profiles["enterprise_router"] = {
        "model_provider": "enterprise_router",
        "model": model,
    }
    existing["profiles"] = profiles

    # Write back
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        def _toml_value(v: object) -> str:
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, str):
                return json.dumps(v, ensure_ascii=False)
            if isinstance(v, (int, float)):
                return str(v)
            if isinstance(v, list):
                return "[" + ", ".join(_toml_value(item) for item in v) + "]"
            return str(v)

        def _toml_key(k: str) -> str:
            """Quote a TOML key segment if it contains special characters."""
            if all(c.isalnum() or c in "-_" for c in k):
                return k
            escaped = k.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'

        def _write_table(path: list[str], table: dict) -> None:  # type: ignore[type-arg]
            scalars = [(key, value) for key, value in table.items() if not isinstance(value, dict)]
            children = [(key, value) for key, value in table.items() if isinstance(value, dict)]

            if path:
                f.write("\n[" + ".".join(_toml_key(part) for part in path) + "]\n")
            for key, value in scalars:
                if value is None:
                    continue
                f.write(f"{_toml_key(str(key))} = {_toml_value(value)}\n")
            for key, value in children:
                _write_table([*path, str(key)], value)

        root_scalars = {
            key: value for key, value in existing.items() if not isinstance(value, dict)
        }
        for key, value in root_scalars.items():
            if value is None:
                continue
            f.write(f"{_toml_key(str(key))} = {_toml_value(value)}\n")

        for key, value in existing.items():
            if isinstance(value, dict):
                _write_table([str(key)], value)

    return env_file, config_path


def _write_claude_code_env(
    *,
    home_dir: Path,
    router_public_base_url: str,
    access_token: str,
    model: str,
) -> Path:
    claude_base_url = _claude_code_base_url(router_public_base_url)
    env_dir = home_dir / ".enterprise-llm-proxy"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_file = env_dir / "claude-code.env"
    lines = [
        f'export ANTHROPIC_BASE_URL="{claude_base_url}"',
        f'export ANTHROPIC_AUTH_TOKEN="{access_token}"',
        "unset ANTHROPIC_API_KEY",
        f'export ANTHROPIC_MODEL="{model}"',
    ]
    if _is_native_claude_model(model):
        lines.extend(
            [
                "unset ANTHROPIC_CUSTOM_MODEL_OPTION",
                "unset ANTHROPIC_CUSTOM_MODEL_OPTION_NAME",
                "unset ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION",
            ]
        )
    else:
        lines.append(f'export ANTHROPIC_CUSTOM_MODEL_OPTION="{model}"')

    if _is_loopback_router_host(claude_base_url):
        router_host = urlparse(claude_base_url).hostname or "localhost"
        lines.append(f'export NO_PROXY="{router_host},localhost,127.0.0.1"')
        lines.append('export no_proxy="$NO_PROXY"')
        local_ca_file = env_dir / "router-local-ca.pem"
        if sys.platform == "darwin" and _export_local_ca_certificate(local_ca_file):
            lines.append(f'export NODE_EXTRA_CA_CERTS="{local_ca_file}"')

    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_file


def _open_browser_or_print(url: str) -> None:
    """Open browser if in a graphical environment, otherwise print URL for manual copy."""
    # macOS: `open` works even from SSH sessions that forward a display
    if sys.platform == "darwin":
        import subprocess as _sp
        result = _sp.run(["open", url])
        if result.returncode == 0:
            return
    # Headless / remote: print for manual copy
    in_ssh = bool(os.environ.get("SSH_TTY") or os.environ.get("SSH_CONNECTION"))
    headless = not os.environ.get("DISPLAY", "").strip()
    if in_ssh or headless:
        print(f"\n无法自动打开浏览器。请手动访问以下地址完成授权:\n\n  {url}\n")
        return
    if not webbrowser.open(url):
        print(f"\n浏览器打开失败，请手动访问:\n\n  {url}\n")


def _choose_open_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _run_browser_login(
    *,
    api_client: RouterctlApiClient,
    router_base_url: str,
    ca_bundle: str | None,
    insecure: bool,
    timeout_seconds: int,
) -> dict[str, object]:
    port = _choose_open_port()
    redirect_uri = f"http://localhost:{port}/callback"
    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = api_client.build_pkce_pair()
    start = api_client.start_cli_auth(
        router_base_url=router_base_url,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        ca_bundle=ca_bundle,
        insecure=insecure,
    )

    callback: dict[str, str] = {}
    received = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            callback["code"] = params.get("code", [""])[0]
            callback["state"] = params.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<html><body><h1>routerctl 登录完成</h1><p>你可以回到终端了。</p></body></html>".encode(
                    "utf-8"
                )
            )
            received.set()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args

    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _open_browser_or_print(str(start["browser_url"]))
        if not received.wait(timeout=timeout_seconds):
            raise RuntimeError("等待浏览器登录超时，请重试")
    finally:
        server.shutdown()
        thread.join(timeout=1)
        server.server_close()

    if callback.get("state") != state or not callback.get("code"):
        raise RuntimeError("浏览器登录回调无效，请重试")

    return api_client.exchange_cli_auth(
        router_base_url=router_base_url,
        code=callback["code"],
        code_verifier=code_verifier,
        ca_bundle=ca_bundle,
        insecure=insecure,
    )


def _client_support_label(supported_clients: object) -> str:
    if not isinstance(supported_clients, list):
        return "—"
    labels: list[str] = []
    for client in supported_clients:
        value = str(client)
        if value == "claude_code":
            labels.append("claude")
        elif value == "codex":
            labels.append("codex")
        else:
            labels.append(value)
    return ", ".join(labels) if labels else "—"


def _model_supports_client(model: dict[str, object], client_name: str) -> bool:
    supported_clients = model.get("supported_clients", [])
    if not isinstance(supported_clients, list):
        return False
    expected = "claude_code" if client_name == "claude" else "codex"
    return expected in [str(item) for item in supported_clients]


def _print_available_models(models: list[dict[str, object]], *, default_model: str | None = None) -> None:
    if not models:
        print("当前没有可路由模型。", file=sys.stderr)
        return
    for index, model in enumerate(models, start=1):
        model_id = str(model.get("id", ""))
        display_name = str(model.get("display_name", model_id))
        provider = str(model.get("provider", ""))
        source = str(model.get("source", "unknown"))
        clients = _client_support_label(model.get("supported_clients"))
        default_suffix = " [default]" if default_model and model_id == default_model else ""
        routable = model.get("routable", True)
        unavailable_reason = model.get("unavailable_reason")
        print(f"[{index}] {display_name}{default_suffix}")
        print(f"    id: {model_id}")
        print(f"    provider: {provider}")
        print(f"    clients: {clients}")
        print(f"    source: {source}")
        if routable is False and unavailable_reason:
            print(f"    status: unavailable ({unavailable_reason})")


def _prompt_number(prompt: str, *, minimum: int, maximum: int) -> int:
    while True:
        raw = input(prompt).strip()
        try:
            choice = int(raw)
        except ValueError:
            print(f"请输入 {minimum}-{maximum} 之间的数字。", file=sys.stderr)
            continue
        if minimum <= choice <= maximum:
            return choice
        print(f"请输入 {minimum}-{maximum} 之间的数字。", file=sys.stderr)


def _choose_action() -> str:
    print("选择操作：", file=sys.stderr)
    print("  1) 保存为默认模型", file=sys.stderr)
    choice = _prompt_number("请输入选项编号: ", minimum=1, maximum=1)
    return {1: "save"}[choice]


def _choose_model(
    models: list[dict[str, object]],
    *,
    default_model: str | None = None,
) -> dict[str, object]:
    _print_available_models(models, default_model=default_model)
    choice = _prompt_number("请输入模型编号: ", minimum=1, maximum=len(models))
    return models[choice - 1]


def _print_cc_switch_guidance(client_name: str) -> None:
    print(
        "routerctl no longer launches coding CLIs directly; use cc-switch to start/switch models.",
        file=sys.stderr,
    )
    print(
        f"routerctl only keeps credential import/bind flows, e.g. `routerctl {client_name} bind`.",
        file=sys.stderr,
    )


def _build_claude_bind_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="routerctl claude bind",
        description="Import the local Claude Code OAuth credential into the enterprise Router",
        epilog=(
            "Examples:\n"
            "  routerctl claude bind\n"
            "  routerctl claude bind --share\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--session-file",
        default=None,
    )
    parser.add_argument(
        "--ca-bundle",
        default=None,
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--share",
        action="store_true",
        default=False,
        help="Immediately promote the imported credential into the enterprise pool",
    )
    return parser


def _normalize_claude_args(args: argparse.Namespace) -> None:
    claude_args = list(getattr(args, "claude_args", None) or [])
    if claude_args and claude_args[0] == "bind":
        bind_args = _build_claude_bind_parser().parse_args(claude_args[1:])
        args.claude_command = "bind"
        args.claude_args = []
        args.session_file = bind_args.session_file or args.session_file
        args.ca_bundle = bind_args.ca_bundle or args.ca_bundle
        args.insecure = args.insecure or bind_args.insecure
        args.share = bind_args.share
        return

    args.claude_command = None
    args.claude_args = claude_args


def _prepare_claude_passthrough_argv(argv: list[str]) -> list[str]:
    if not argv or argv[0] != "claude":
        return argv

    options_with_values = {"--model", "--session-file", "--ca-bundle"}
    flags = {"--insecure", "-h", "--help"}
    index = 1
    while index < len(argv):
        token = argv[index]
        if token == "--" or token == "bind":
            return argv
        if token in flags:
            index += 1
            continue
        if token in options_with_values:
            index += 2
            continue
        if any(token.startswith(f"{option}=") for option in options_with_values):
            index += 1
            continue
        return [*argv[:index], "--", *argv[index:]]

    return argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="routerctl",
        epilog=(
            "Examples:\n"
            "  routerctl auth login --router-base-url https://router.example.com\n"
            "  routerctl auth status\n"
            "  routerctl claude bind\n"
            "  routerctl codex\n"
            "  routerctl codex bind\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    auth_parser = subparsers.add_parser("auth", help="Manage routerctl login sessions")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command")

    bootstrap_parser = auth_subparsers.add_parser(
        "bootstrap",
        help="Exchange a one-time bootstrap token for a local CLI session",
    )
    bootstrap_parser.add_argument(
        "--router-base-url",
        required=False,
        default=os.environ.get("ENTERPRISE_LLM_PROXY_ROUTER_BASE_URL"),
    )
    bootstrap_parser.add_argument(
        "--bootstrap-token",
        required=False,
        default=os.environ.get("ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN"),
    )
    bootstrap_parser.add_argument(
        "--session-file",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_SESSION_FILE"),
    )
    bootstrap_parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CA_BUNDLE"),
    )
    bootstrap_parser.add_argument(
        "--insecure",
        action="store_true",
        default=_env_flag("ENTERPRISE_LLM_PROXY_INSECURE_SKIP_VERIFY"),
    )

    login_parser = auth_subparsers.add_parser(
        "login",
        help="Open the browser and sign in to the enterprise Router",
    )
    login_parser.add_argument(
        "--router-base-url",
        required=False,
        default=os.environ.get("ENTERPRISE_LLM_PROXY_ROUTER_BASE_URL"),
    )
    login_parser.add_argument(
        "--session-file",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_SESSION_FILE"),
    )
    login_parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CA_BUNDLE"),
    )
    login_parser.add_argument(
        "--insecure",
        action="store_true",
        default=_env_flag("ENTERPRISE_LLM_PROXY_INSECURE_SKIP_VERIFY"),
    )
    login_parser.add_argument("--timeout-seconds", type=int, default=300)

    status_parser = auth_subparsers.add_parser("status", help="Print the current login session")
    status_parser.add_argument(
        "--session-file",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_SESSION_FILE"),
    )

    logout_parser = auth_subparsers.add_parser("logout", help="Clear the local login session")
    logout_parser.add_argument(
        "--session-file",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_SESSION_FILE"),
    )

    activate_parser = subparsers.add_parser(
        "activate",
        help="[DEPRECATED] Persistent activation. Use cc-switch for client launch/model switching instead.",
    )
    activate_subparsers = activate_parser.add_subparsers(dest="activate_command")
    for command_name in ("claude-code", "codex"):
        subparser = activate_subparsers.add_parser(command_name, help=f"Activate {command_name}")
        subparser.add_argument("--model", required=False, default="")
        subparser.add_argument(
            "--session-file",
            default=os.environ.get("ENTERPRISE_LLM_PROXY_SESSION_FILE"),
        )
        subparser.add_argument(
            "--ca-bundle",
            default=os.environ.get("ENTERPRISE_LLM_PROXY_CA_BUNDLE"),
        )
        subparser.add_argument(
            "--insecure",
            action="store_true",
            default=_env_flag("ENTERPRISE_LLM_PROXY_INSECURE_SKIP_VERIFY"),
        )

    claude_parser = subparsers.add_parser(
        "claude",
        help="Bind Claude Code credentials into the enterprise Router (launch via cc-switch)",
    )
    claude_parser.add_argument(
        "--model",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_DEFAULT_MODEL", ""),
        help="Model to use (default: server default_claude_model)",
    )
    claude_parser.add_argument(
        "--session-file",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_SESSION_FILE"),
    )
    claude_parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CA_BUNDLE"),
    )
    claude_parser.add_argument(
        "--insecure",
        action="store_true",
        default=_env_flag("ENTERPRISE_LLM_PROXY_INSECURE_SKIP_VERIFY"),
    )
    claude_parser.add_argument(
        "claude_args",
        nargs=argparse.REMAINDER,
        help=(
            "Deprecated launch arguments. "
            "Use cc-switch to launch/switch models, and `routerctl claude bind` for credential import."
        ),
    )

    codex_parser = subparsers.add_parser(
        "codex",
        help="Bind Codex credentials into the enterprise Router (launch via cc-switch)",
    )
    codex_parser.add_argument(
        "--model",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_DEFAULT_MODEL", ""),
        help="Model to use (default: server default_codex_model)",
    )
    codex_parser.add_argument(
        "--session-file",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_SESSION_FILE"),
    )
    codex_parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CA_BUNDLE"),
    )
    codex_parser.add_argument(
        "--insecure",
        action="store_true",
        default=_env_flag("ENTERPRISE_LLM_PROXY_INSECURE_SKIP_VERIFY"),
    )
    codex_parser.add_argument(
        "--codex-bin",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CODEX_BIN", "codex"),
    )
    codex_subparsers = codex_parser.add_subparsers(dest="codex_command")
    codex_parser.add_argument(
        "codex_args",
        nargs=argparse.REMAINDER,
        help="Deprecated launch arguments. Use cc-switch to launch/switch models.",
    )
    import_parser = codex_subparsers.add_parser(
        "import",
        help="Import a local Codex ChatGPT login using a platform API key",
    )
    import_parser.add_argument(
        "--router-base-url",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_ROUTER_BASE_URL"),
    )
    import_parser.add_argument(
        "--router-api-key",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_API_KEY"),
    )
    import_parser.add_argument(
        "--codex-bin",
        default="codex",
    )
    import_parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CA_BUNDLE"),
    )
    import_parser.add_argument(
        "--insecure",
        action="store_true",
        default=_env_flag("ENTERPRISE_LLM_PROXY_INSECURE_SKIP_VERIFY"),
    )
    bind_parser = codex_subparsers.add_parser(
        "bind",
        help="Bind a local Codex / ChatGPT login into the enterprise Router",
        epilog=(
            "Examples:\n"
            "  routerctl codex bind\n"
            "  routerctl codex bind --codex-bin /usr/local/bin/codex\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    bind_parser.add_argument(
        "--session-file",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_SESSION_FILE"),
    )
    bind_parser.add_argument(
        "--codex-bin",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CODEX_BIN", "codex"),
    )
    bind_parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CA_BUNDLE"),
    )
    bind_parser.add_argument(
        "--insecure",
        action="store_true",
        default=_env_flag("ENTERPRISE_LLM_PROXY_INSECURE_SKIP_VERIFY"),
    )

    models_parser = subparsers.add_parser(
        "models",
        help="List currently routable models and interactively configure a default model",
    )
    models_parser.set_defaults(models_command="list")
    models_parser.add_argument(
        "--session-file",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_SESSION_FILE"),
    )
    models_parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CA_BUNDLE"),
    )
    models_parser.add_argument(
        "--insecure",
        action="store_true",
        default=_env_flag("ENTERPRISE_LLM_PROXY_INSECURE_SKIP_VERIFY"),
    )
    models_parser.add_argument(
        "--codex-bin",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CODEX_BIN", "codex"),
    )
    models_subparsers = models_parser.add_subparsers(dest="models_command")

    models_list_parser = models_subparsers.add_parser(
        "list",
        help="List models that are currently routable for the logged-in session",
    )
    models_list_parser.add_argument(
        "--session-file",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_SESSION_FILE"),
    )
    models_list_parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CA_BUNDLE"),
    )
    models_list_parser.add_argument(
        "--insecure",
        action="store_true",
        default=_env_flag("ENTERPRISE_LLM_PROXY_INSECURE_SKIP_VERIFY"),
    )
    models_list_parser.add_argument(
        "--client",
        choices=["claude", "codex"],
        default=None,
    )
    models_list_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
    )

    models_config_parser = models_subparsers.add_parser(
        "config",
        help="Interactively choose and save a routable default model",
    )
    models_config_parser.add_argument(
        "--session-file",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_SESSION_FILE"),
    )
    models_config_parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CA_BUNDLE"),
    )
    models_config_parser.add_argument(
        "--insecure",
        action="store_true",
        default=_env_flag("ENTERPRISE_LLM_PROXY_INSECURE_SKIP_VERIFY"),
    )
    models_config_parser.add_argument(
        "--codex-bin",
        default=os.environ.get("ENTERPRISE_LLM_PROXY_CODEX_BIN", "codex"),
    )
    models_config_parser.add_argument(
        "--client",
        choices=["claude", "codex"],
        default=None,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = sys.argv[1:] if argv is None else list(argv)
    args = parser.parse_args(_prepare_claude_passthrough_argv(raw_argv))
    if args.command == "claude":
        _normalize_claude_args(args)
    api_client = RouterctlApiClient()

    try:
        if args.command == "auth" and args.auth_command == "bootstrap":
            if not args.router_base_url:
                parser.error("--router-base-url is required")
            if not args.bootstrap_token:
                parser.error("--bootstrap-token is required")
            store = _session_store(args.session_file)
            payload = api_client.exchange_bootstrap(
                router_base_url=args.router_base_url,
                bootstrap_token=args.bootstrap_token,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
            )
            session = RouterctlSession(
                router_base_url=args.router_base_url.rstrip("/"),
                access_token=str(payload["access_token"]),
                expires_at=payload.get("expires_at") and str(payload["expires_at"]),
                principal=dict(payload["principal"]),
            )
            store.save(session)
            print(json.dumps(session.to_dict(), ensure_ascii=False))
            print(f"routerctl 已登录：{session.principal.get('email', 'unknown')}", file=sys.stderr)
            return 0

        if args.command == "auth" and args.auth_command == "login":
            if not args.router_base_url:
                parser.error("--router-base-url is required")
            store = _session_store(args.session_file)
            payload = _run_browser_login(
                api_client=api_client,
                router_base_url=args.router_base_url,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
                timeout_seconds=args.timeout_seconds,
            )
            session = RouterctlSession(
                router_base_url=args.router_base_url.rstrip("/"),
                access_token=str(payload["access_token"]),
                expires_at=payload.get("expires_at") and str(payload["expires_at"]),
                principal=dict(payload["principal"]),
            )
            store.save(session)
            print(json.dumps(session.to_dict(), ensure_ascii=False))
            print(f"routerctl 已登录：{session.principal.get('email', 'unknown')}", file=sys.stderr)
            return 0

        if args.command == "auth" and args.auth_command == "status":
            store = _session_store(args.session_file)
            session = _load_session(store)
            if session is None:
                print("NOT_AUTHENTICATED: 未找到登录会话", file=sys.stderr)
                return EXIT_AUTH
            print(json.dumps(session.to_dict(), ensure_ascii=False, indent=2))
            return 0

        if args.command == "auth" and args.auth_command == "logout":
            store = _session_store(args.session_file)
            session = store.load()
            if session is not None:
                try:
                    api_client.server_logout(
                        router_base_url=session.router_base_url,
                        token=session.access_token,
                    )
                except Exception:
                    pass  # server unreachable — local logout still proceeds
            store.clear()
            print(json.dumps({"ok": True}))
            print("routerctl 已退出登录", file=sys.stderr)
            return EXIT_OK

        if args.command == "models" and args.models_command == "list":
            store = _session_store(args.session_file)
            session = _ensure_fresh_session(
                store=store,
                api_client=api_client,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
            )

            def list_models_action(active_session: RouterctlSession) -> list[dict[str, object]]:
                return api_client.list_cli_models(
                    router_base_url=active_session.router_base_url,
                    cli_session_token=active_session.access_token,
                    ca_bundle=args.ca_bundle,
                    insecure=args.insecure,
                )

            models = _retry_once_after_reauth(
                store=store,
                api_client=api_client,
                session=session,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
                action=list_models_action,
            )
            if getattr(args, "client", None):
                models = [model for model in models if _model_supports_client(model, args.client)]
            if getattr(args, "json", False):
                print(json.dumps({"data": models}, ensure_ascii=False, indent=2))
            else:
                default_model = None
                try:
                    prefs = api_client.get_preferences(
                        router_base_url=session.router_base_url,
                        cli_session_token=session.access_token,
                        ca_bundle=args.ca_bundle,
                        insecure=args.insecure,
                    )
                    default_model = prefs.get("default_model") and str(prefs["default_model"])
                except Exception:
                    default_model = None
                _print_available_models(models, default_model=default_model)
            return EXIT_OK

        if args.command == "models" and args.models_command == "config":
            store = _session_store(args.session_file)
            session = _ensure_fresh_session(
                store=store,
                api_client=api_client,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
            )
            action = _choose_action()

            def list_models_action(active_session: RouterctlSession) -> list[dict[str, object]]:
                return api_client.list_cli_models(
                    router_base_url=active_session.router_base_url,
                    cli_session_token=active_session.access_token,
                    ca_bundle=args.ca_bundle,
                    insecure=args.insecure,
                )

            models = _retry_once_after_reauth(
                store=store,
                api_client=api_client,
                session=session,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
                action=list_models_action,
            )
            session = store.load() or session
            default_model = None
            try:
                prefs = api_client.get_preferences(
                    router_base_url=session.router_base_url,
                    cli_session_token=session.access_token,
                    ca_bundle=args.ca_bundle,
                    insecure=args.insecure,
                )
                default_model = prefs.get("default_model") and str(prefs["default_model"])
            except Exception:
                default_model = None

            models = [model for model in models if model.get("routable", True) is not False]

            if not models:
                print("当前没有可路由模型。", file=sys.stderr)
                return EXIT_ERROR

            selected_model = _choose_model(models, default_model=default_model)
            selected_model_id = str(selected_model["id"])

            def patch_preferences_action(active_session: RouterctlSession) -> dict[str, object]:
                return api_client.patch_preferences(
                    router_base_url=active_session.router_base_url,
                    cli_session_token=active_session.access_token,
                    default_model=selected_model_id,
                    ca_bundle=args.ca_bundle,
                    insecure=args.insecure,
                )

            _retry_once_after_reauth(
                store=store,
                api_client=api_client,
                session=session,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
                action=patch_preferences_action,
            )
            print(f"默认模型已保存：{selected_model_id}", file=sys.stderr)

            print(json.dumps({"default_model": selected_model_id}, ensure_ascii=False))
            return EXIT_OK

        if args.command == "activate" and args.activate_command in {"claude-code", "codex"}:
            print(
                "DEPRECATED: `routerctl activate` 已废弃。"
                " 请改用 cc-switch 启动/切换 Coding CLI；routerctl 只保留 auth 和 bind。",
                file=sys.stderr,
            )
            store = _session_store(args.session_file)
            session = _ensure_fresh_session(
                store=store,
                api_client=api_client,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
            )

            def activate_action(active_session: RouterctlSession) -> dict[str, object]:
                return api_client.activate_client(
                    router_base_url=active_session.router_base_url,
                    cli_session_token=active_session.access_token,
                    client=args.activate_command,
                    model=args.model,
                    ca_bundle=args.ca_bundle,
                    insecure=args.insecure,
                )

            payload = _retry_once_after_reauth(
                store=store,
                api_client=api_client,
                session=session,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
                action=activate_action,
            )
            home_dir = Path.home()
            if args.activate_command == "claude-code":
                env_file = _write_claude_code_env(
                    home_dir=home_dir,
                    router_public_base_url=str(payload["router_public_base_url"]),
                    access_token=str(payload["access_token"]),
                    model=str(payload["model"]),
                )
                print(json.dumps({"env_file": str(env_file)}))
                print(f"Claude Code 已激活。运行: source {env_file}", file=sys.stderr)
                return EXIT_OK

            env_file, config_file = _write_codex_activation(
                home_dir=home_dir,
                router_public_base_url=str(payload["router_public_base_url"]),
                access_token=str(payload["access_token"]),
                model=str(payload["model"]),
            )
            print(json.dumps({"env_file": str(env_file), "config_file": str(config_file)}))
            print(f"Codex 已激活。运行: source {env_file}", file=sys.stderr)
            return EXIT_OK

        if args.command == "claude" and getattr(args, "claude_command", None) == "bind":
            store = _session_store(args.session_file)
            if _load_session(store) is None:
                _print_not_authenticated()
                return EXIT_AUTH
            session = _ensure_fresh_session(
                store=store,
                api_client=api_client,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
            )
            importer = ClaudeCodeCliImporter()

            def bind_action(active_session: RouterctlSession) -> dict[str, object]:
                return importer.import_with_cli_session(
                    router_base_url=active_session.router_base_url,
                    cli_session_token=active_session.access_token,
                    ca_bundle=args.ca_bundle,
                    insecure=args.insecure,
                )

            result = _retry_once_after_reauth(
                store=store,
                api_client=api_client,
                session=session,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
                action=bind_action,
            )
            if getattr(args, "share", False):
                def share_action(active_session: RouterctlSession) -> dict[str, object]:
                    return api_client.share_upstream_credential(
                        router_base_url=active_session.router_base_url,
                        cli_session_token=active_session.access_token,
                        credential_id=str(result["id"]),
                        ca_bundle=args.ca_bundle,
                        insecure=args.insecure,
                    )

                result = _retry_once_after_reauth(
                    store=store,
                    api_client=api_client,
                    session=store.load() or session,
                    ca_bundle=args.ca_bundle,
                    insecure=args.insecure,
                    action=share_action,
                )
            _print_claude_bind_result(result)
            return EXIT_OK

        if args.command == "claude" and not getattr(args, "claude_command", None):
            _print_cc_switch_guidance("claude")
            return EXIT_ERROR

        if args.command == "codex" and not getattr(args, "codex_command", None):
            _print_cc_switch_guidance("codex")
            return EXIT_ERROR

        if args.command == "codex" and args.codex_command == "bind":
            if shutil.which(args.codex_bin) is None:
                print(
                    f"BINARY_NOT_FOUND: '{args.codex_bin}' 未安装。"
                    " 修复: 安装 Codex (https://github.com/openai/codex) 后重试。(不可重试)",
                    file=sys.stderr,
                )
                return EXIT_NOT_FOUND
            store = _session_store(args.session_file)
            if _load_session(store) is None:
                _print_not_authenticated()
                return EXIT_AUTH
            session = _ensure_fresh_session(
                store=store,
                api_client=api_client,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
            )
            importer = CodexCliImporter(codex_bin=args.codex_bin)
            def bind_action(active_session: RouterctlSession) -> dict[str, object]:
                return importer.import_with_cli_session(
                    router_base_url=active_session.router_base_url,
                    cli_session_token=active_session.access_token,
                    ca_bundle=args.ca_bundle,
                    insecure=args.insecure,
                )

            result = _retry_once_after_reauth(
                store=store,
                api_client=api_client,
                session=session,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
                action=bind_action,
            )
            _print_codex_bind_result(result)
            return EXIT_OK

        if args.command == "codex" and args.codex_command == "import":
            if not args.router_base_url:
                parser.error("--router-base-url is required or set ENTERPRISE_LLM_PROXY_ROUTER_BASE_URL")
            if not args.router_api_key:
                parser.error("--router-api-key is required or set ENTERPRISE_LLM_PROXY_API_KEY")

            if shutil.which(args.codex_bin) is None:
                print(
                    f"BINARY_NOT_FOUND: '{args.codex_bin}' 未安装。"
                    " 修复: 安装 Codex (https://github.com/openai/codex) 后重试。(不可重试)",
                    file=sys.stderr,
                )
                return EXIT_NOT_FOUND

            importer = CodexCliImporter(codex_bin=args.codex_bin)
            result = importer.import_credential(
                router_base_url=args.router_base_url,
                router_api_key=args.router_api_key,
                ca_bundle=args.ca_bundle,
                insecure=args.insecure,
            )
            print(json.dumps(result, ensure_ascii=False))
            return EXIT_OK
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
