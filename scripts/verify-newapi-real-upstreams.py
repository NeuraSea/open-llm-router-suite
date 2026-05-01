#!/usr/bin/env python3
"""Run real upstream smokes through Router and router-synced New API channels.

The script intentionally reads secrets only from environment variables or a
routerctl session file and never prints credential values.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CODEX_MODEL = "gpt-5.4"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"


class SmokeError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmokeConfig:
    newapi_base_url: str
    router_base_url: str | None
    router_v1_base_url: str | None
    api_headers: dict[str, str]
    router_headers: dict[str, str]
    private_token_key: str | None
    private_group: str | None
    codex_model: str
    claude_model: str
    codex_stream: bool
    run_codex: bool
    run_claude: bool
    run_router_compat: bool
    router_model_filters: tuple[str, ...]
    router_max_tokens: int
    continue_on_router_error: bool
    check_router_credentials: bool
    keep_token: bool
    timeout_seconds: float
    ssl_context: ssl.SSLContext | None


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise SmokeError(f"env file not found: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def load_router_session_token(session_file: Path) -> str | None:
    if not session_file.exists():
        return None
    try:
        payload = json.loads(session_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SmokeError(f"routerctl session file is not valid JSON: {session_file}") from exc
    token = payload.get("access_token")
    if isinstance(token, str) and token.strip():
        return token.strip()
    return None


def build_config(args: argparse.Namespace) -> SmokeConfig:
    for env_file in args.env_file or []:
        load_env_file(Path(env_file).expanduser())

    router_base_url = first_env("ROUTER_BASE_URL", "ENTERPRISE_LLM_PROXY_ROUTER_PUBLIC_BASE_URL")
    newapi_base_url = (
        first_env("NEWAPI_BASE_URL", "ENTERPRISE_LLM_PROXY_NEWAPI_PUBLIC_BASE_URL", "API_NEW_BASE_URL")
        or router_base_url
    )
    if not newapi_base_url and not args.skip_router_compat:
        raise SmokeError(
            "NEWAPI_BASE_URL is required, or set ENTERPRISE_LLM_PROXY_ROUTER_PUBLIC_BASE_URL/ROUTER_BASE_URL"
        )
    if (not args.skip_codex or not args.skip_claude) and not newapi_base_url:
        raise SmokeError("NEWAPI_BASE_URL is required for Codex/Claude New API smoke")

    router_session_file = Path(
        os.getenv("ROUTERCTL_SESSION_FILE", "~/.enterprise-llm-proxy/session.json")
    ).expanduser()
    router_token = first_env("ROUTER_SESSION_TOKEN") or load_router_session_token(router_session_file)
    router_api_key = (
        first_env("ROUTER_PLATFORM_API_KEY", "ROUTER_API_KEY", "ROUTER_OPENAI_API_KEY")
        or first_elp_env("ENTERPRISE_LLM_PROXY_PLATFORM_API_KEY", "OPENAI_API_KEY")
    )
    session_cookie = first_env("NEWAPI_SESSION_COOKIE")
    private_token_key = first_env("NEWAPI_PRIVATE_TOKEN_KEY", "PRIVATE_TOKEN_KEY")

    api_headers: dict[str, str] = {}
    if session_cookie:
        api_headers["Cookie"] = f"session={session_cookie}"
    elif router_token:
        api_headers["Authorization"] = f"Bearer {router_token}"
    elif (not args.skip_codex or not args.skip_claude) and not private_token_key:
        raise SmokeError(
            "set NEWAPI_SESSION_COOKIE, ROUTER_SESSION_TOKEN, a routerctl session file, "
            "or NEWAPI_PRIVATE_TOKEN_KEY"
        )

    router_headers: dict[str, str] = {}
    if router_api_key:
        router_headers["Authorization"] = f"Bearer {router_api_key}"
    elif router_token:
        router_headers["Authorization"] = f"Bearer {router_token}"

    verify_tls = os.getenv("VERIFY_NEWAPI_TLS", "true").lower() not in {"0", "false", "no"}
    ssl_context = None if verify_tls and not args.insecure else ssl._create_unverified_context()
    router_origin = normalize_gateway_base_url(router_base_url) if router_base_url else None
    router_v1_base_url = normalize_router_v1_base_url(
        first_env("ROUTER_V1_BASE_URL", "ROUTER_OPENAI_BASE_URL", "ENTERPRISE_LLM_PROXY_ROUTER_PUBLIC_BASE_URL")
        or (router_origin + "/v1" if router_origin else "")
    )
    filters = tuple(
        item.strip().lower()
        for raw in args.router_model_filter
        for item in raw.split(",")
        if item.strip()
    )

    return SmokeConfig(
        newapi_base_url=normalize_gateway_base_url(newapi_base_url) if newapi_base_url else "",
        router_base_url=router_origin,
        router_v1_base_url=router_v1_base_url,
        api_headers=api_headers,
        router_headers=router_headers,
        private_token_key=private_token_key,
        private_group=first_env("PRIVATE_GROUP", "NEWAPI_PRIVATE_GROUP"),
        codex_model=os.getenv("CODEX_MODEL", DEFAULT_CODEX_MODEL),
        claude_model=os.getenv("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL),
        codex_stream=os.getenv("CODEX_STREAM", "true").lower() not in {"0", "false", "no"},
        run_codex=not args.skip_codex,
        run_claude=not args.skip_claude,
        run_router_compat=not args.skip_router_compat,
        router_model_filters=filters or ("lmstudio", "glm"),
        router_max_tokens=args.router_max_tokens,
        continue_on_router_error=args.continue_on_router_error,
        check_router_credentials=not args.skip_router_credential_check,
        keep_token=args.keep_token,
        timeout_seconds=args.timeout,
        ssl_context=ssl_context,
    )


def first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def first_elp_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip().startswith("elp_"):
            return value.strip()
    return None


def normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def normalize_gateway_base_url(value: str) -> str:
    base_url = normalize_base_url(value)
    if base_url.endswith("/v1"):
        return base_url[:-3]
    return base_url


def normalize_router_v1_base_url(value: str) -> str | None:
    if not value:
        return None
    base_url = normalize_base_url(value)
    if base_url.endswith("/v1"):
        return base_url
    return base_url + "/v1"


def request_json(
    config: SmokeConfig,
    method: str,
    path_or_url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    status, body = request_bytes(
        config,
        method,
        path_or_url,
        headers=headers,
        payload=payload,
    )
    try:
        parsed = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise SmokeError(f"{method} {path_or_url} returned non-JSON body: {body[:300]!r}") from exc
    return status, parsed


def request_bytes(
    config: SmokeConfig,
    method: str,
    path_or_url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, bytes]:
    url = path_or_url if path_or_url.startswith("http") else config.newapi_base_url + path_or_url
    body = None
    merged_headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 router-real-upstream-smoke",
        **(headers or {}),
    }
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        merged_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=merged_headers, method=method)
    try:
        with urllib.request.urlopen(
            req,
            timeout=config.timeout_seconds,
            context=config.ssl_context,
        ) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        error_body = exc.read()
        raise SmokeError(
            f"{method} {redact_url(url)} failed with HTTP {exc.code}: {summarize_body(error_body)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SmokeError(f"{method} {redact_url(url)} failed: {exc.reason}") from exc


def summarize_body(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace").replace("\n", " ")
    if len(text) > 500:
        return text[:500] + "..."
    return text


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted_query = urllib.parse.urlencode(
        [
            (key, "***" if "token" in key.lower() or "key" in key.lower() else value)
            for key, value in query
        ]
    )
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, redacted_query, ""))


def api_request_json(
    config: SmokeConfig,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _, parsed = request_json(
        config,
        method,
        path,
        headers=config.api_headers,
        payload=payload,
    )
    if parsed.get("success") is False:
        raise SmokeError(f"{method} {path} returned success=false: {parsed.get('message')}")
    return parsed


def discover_private_group(config: SmokeConfig) -> str:
    if config.private_group:
        return config.private_group
    parsed = api_request_json(config, "GET", "/api/user/self")
    group = parsed.get("data", {}).get("group")
    if not isinstance(group, str) or not group:
        raise SmokeError("/api/user/self did not return data.group; set PRIVATE_GROUP explicitly")
    return group


def list_router_credentials(config: SmokeConfig) -> None:
    if not config.check_router_credentials:
        print("router credentials: skipped by request")
        return
    if not config.router_base_url or "Authorization" not in config.api_headers:
        print("router credentials: skipped (no Router bearer auth)")
        return
    _, parsed = request_json(
        config,
        "GET",
        config.router_base_url + "/me/upstream-credentials",
        headers={"Authorization": config.api_headers["Authorization"]},
    )
    credentials = parsed.get("data")
    if not isinstance(credentials, list):
        raise SmokeError("Router credential list response missing data[]")
    providers = {
        item.get("provider")
        for item in credentials
        if isinstance(item, dict) and item.get("visibility") in {"private", "enterprise_pool"}
    }
    missing = {"openai-codex", "claude-max"} - providers
    if missing:
        raise SmokeError(f"missing bound Router credential provider(s): {', '.join(sorted(missing))}")
    print("router credentials: openai-codex and claude-max present")


def find_existing_token(config: SmokeConfig, name: str) -> tuple[int, str] | None:
    parsed = api_request_json(
        config,
        "GET",
        "/api/token/?p=1&size=100",
    )
    items = parsed.get("data", {}).get("items", [])
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("name") == name and isinstance(item.get("id"), int):
            token_id = item["id"]
            key_payload = api_request_json(config, "POST", f"/api/token/{token_id}/key")
            key = key_payload.get("data", {}).get("key")
            if isinstance(key, str) and key:
                return token_id, key
    return None


def create_smoke_token(config: SmokeConfig, group: str) -> tuple[int | None, str]:
    if config.private_token_key:
        return None, config.private_token_key

    name = f"router-real-upstream-smoke-{int(time.time())}"
    payload = {
        "name": name,
        "expired_time": -1,
        "remain_quota": 500000,
        "unlimited_quota": True,
        "group": group,
        "model_limits_enabled": False,
    }
    api_request_json(config, "POST", "/api/token/", payload=payload)
    existing = find_existing_token(config, name)
    if existing is None:
        raise SmokeError("created New API smoke token but could not reveal its key")
    print(f"new-api smoke token: created id={existing[0]} group={group}")
    return existing


def delete_smoke_token(config: SmokeConfig, token_id: int | None) -> None:
    if token_id is None or config.keep_token:
        return
    api_request_json(config, "DELETE", f"/api/token/{token_id}")
    print(f"new-api smoke token: deleted id={token_id}")


def call_codex(config: SmokeConfig, token_key: str) -> None:
    request_id = f"real-codex-{int(time.time())}"
    if config.codex_stream:
        _, body = request_bytes(
            config,
            "POST",
            "/v1/responses",
            headers={
                "Authorization": f"Bearer {token_key}",
                "X-Request-Id": request_id,
                "Accept": "text/event-stream",
            },
            payload={
                "model": config.codex_model,
                "input": [{"role": "user", "content": "Reply with OK"}],
                "stream": True,
            },
        )
        text = body.decode("utf-8", errors="replace")
        if "response.completed" not in text and "[DONE]" not in text:
            raise SmokeError("Codex streaming response missing response.completed or [DONE]")
        print(
            "codex real call: ok "
            f"request_id={request_id} model={config.codex_model} stream=true bytes={len(body)}"
        )
        return

    _, parsed = request_json(
        config,
        "POST",
        "/v1/responses",
        headers={
            "Authorization": f"Bearer {token_key}",
            "X-Request-Id": request_id,
        },
        payload={
            "model": config.codex_model,
            "input": [{"role": "user", "content": "Reply with OK"}],
            "stream": False,
        },
    )
    response_id = parsed.get("id")
    usage = parsed.get("usage")
    output_text = parsed.get("output_text")
    output = parsed.get("output")
    if not response_id or not (output_text or output):
        raise SmokeError("Codex response missing id or output text")
    print(
        "codex real call: ok "
        f"request_id={request_id} id={response_id} model={parsed.get('model')} usage_present={usage is not None}"
    )


def call_claude(config: SmokeConfig, token_key: str) -> None:
    request_id = f"real-claude-{int(time.time())}"
    _, parsed = request_json(
        config,
        "POST",
        "/v1/messages",
        headers={
            "Authorization": f"Bearer {token_key}",
            "X-Request-Id": request_id,
        },
        payload={
            "model": config.claude_model,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "Reply with OK"}],
            "stream": False,
        },
    )
    response_id = parsed.get("id")
    content = parsed.get("content")
    has_text = isinstance(content, list) and any(
        isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"]
        for item in content
    )
    if not response_id or not has_text:
        raise SmokeError("Claude response missing id or text content")
    print(
        "claude real call: ok "
        f"request_id={request_id} id={response_id} model={parsed.get('model')} usage_present={parsed.get('usage') is not None}"
    )


def discover_router_compat_models(config: SmokeConfig) -> list[dict[str, Any]]:
    if not config.router_base_url:
        raise SmokeError("ROUTER_BASE_URL or ENTERPRISE_LLM_PROXY_ROUTER_PUBLIC_BASE_URL is required")
    if not config.router_headers:
        raise SmokeError(
            "ROUTER_PLATFORM_API_KEY/ROUTER_API_KEY or a valid ROUTER_SESSION_TOKEN/routerctl session is required"
        )
    validate_router_auth(config)
    _, parsed = request_json(
        config,
        "GET",
        config.router_base_url + "/ui/models?routable_only=true",
        headers=config.router_headers,
    )
    models = parsed.get("data")
    if not isinstance(models, list):
        raise SmokeError("Router /ui/models?routable_only=true response missing data[]")
    selected = [model for model in models if isinstance(model, dict) and router_model_matches(config, model)]
    if not selected:
        filters = ",".join(config.router_model_filters)
        raise SmokeError(f"no routable Router LM Studio/GLM models matched filters: {filters}")
    print(f"router compat models: discovered {len(selected)} target model(s)")
    return selected


def validate_router_auth(config: SmokeConfig) -> None:
    _, parsed = request_json(
        config,
        "GET",
        config.router_base_url + "/ui/session",
        headers=config.router_headers,
    )
    if not isinstance(parsed.get("user_id"), str):
        raise SmokeError("Router /ui/session did not return an authenticated principal")


def router_model_matches(config: SmokeConfig, model: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(model.get(key, ""))
        for key in (
            "id",
            "display_name",
            "provider",
            "provider_alias",
            "model_profile",
            "upstream_model",
            "source",
            "description",
        )
    ).lower()
    return any(token in haystack for token in config.router_model_filters)


def call_router_compat_models(config: SmokeConfig) -> None:
    if not config.router_v1_base_url:
        raise SmokeError("Router /v1 base URL is required")
    models = discover_router_compat_models(config)
    failures: list[tuple[str, str]] = []
    for model in models:
        model_id = str(model.get("id", "")).strip()
        if not model_id:
            raise SmokeError("Router model entry missing id")
        try:
            call_router_chat_completion(config, model_id)
        except SmokeError as exc:
            if not config.continue_on_router_error:
                raise SmokeError(f"Router model {model_id} failed: {exc}") from exc
            failures.append((model_id, str(exc)))
            print(f"router compat real call: failed model={model_id} error={exc}", flush=True)
    if failures:
        failed_models = ", ".join(model_id for model_id, _ in failures)
        raise SmokeError(f"router compat completed with {len(failures)} failure(s): {failed_models}")
    print(f"router compat models: all {len(models)} target model(s) passed", flush=True)


def call_router_chat_completion(config: SmokeConfig, model_id: str) -> None:
    request_id = f"real-router-compat-{int(time.time())}"
    _, parsed = request_json(
        config,
        "POST",
        config.router_v1_base_url + "/chat/completions",
        headers={
            **config.router_headers,
            "X-Request-Id": request_id,
        },
        payload={
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with OK"}],
            "max_tokens": config.router_max_tokens,
            "stream": False,
        },
    )
    choices = parsed.get("choices")
    has_text = isinstance(choices, list) and any(
        isinstance(choice, dict)
        and isinstance(choice.get("message"), dict)
        and (
            (isinstance(choice["message"].get("content"), str) and choice["message"]["content"])
            or (
                isinstance(choice["message"].get("reasoning_content"), str)
                and choice["message"]["reasoning_content"]
            )
        )
        for choice in choices
    )
    if not parsed.get("id") or not has_text:
        raise SmokeError(f"Router model {model_id} response missing id or message content")
    print(
        "router compat real call: ok "
        f"request_id={request_id} model={model_id} id={parsed.get('id')} usage_present={parsed.get('usage') is not None}",
        flush=True,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify router-bound Codex/Anthropic and Router LM Studio/GLM models with real upstream calls."
    )
    parser.add_argument("--env-file", action="append", help="Load env vars from a dotenv-style file.")
    parser.add_argument("--skip-codex", action="store_true", help="Skip /v1/responses Codex smoke.")
    parser.add_argument("--skip-claude", action="store_true", help="Skip /v1/messages Claude smoke.")
    parser.add_argument("--skip-router-compat", action="store_true", help="Skip Router LM Studio/GLM smoke.")
    parser.add_argument(
        "--router-model-filter",
        action="append",
        default=["lmstudio,glm"],
        help="Comma-separated substrings used to select Router routable models. Default: lmstudio,glm.",
    )
    parser.add_argument(
        "--router-max-tokens",
        type=int,
        default=64,
        help="max_tokens for Router LM Studio/GLM chat smoke. Default: 64.",
    )
    parser.add_argument(
        "--continue-on-router-error",
        action="store_true",
        help="Continue Router LM Studio/GLM smoke after per-model failures and summarize them at the end.",
    )
    parser.add_argument(
        "--skip-router-credential-check",
        action="store_true",
        help="Skip /me/upstream-credentials preflight. Useful when NEWAPI_PRIVATE_TOKEN_KEY is already set.",
    )
    parser.add_argument("--keep-token", action="store_true", help="Keep the generated New API smoke token.")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification.")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout per request in seconds.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
        config = build_config(args)
        if not config.run_codex and not config.run_claude and not config.run_router_compat:
            raise SmokeError("nothing to verify: all smoke targets were skipped")

        if config.run_codex or config.run_claude:
            list_router_credentials(config)
            if config.private_token_key:
                token_id, token_key = None, config.private_token_key
                print("new-api smoke token: using NEWAPI_PRIVATE_TOKEN_KEY")
            else:
                group = discover_private_group(config)
                token_id, token_key = create_smoke_token(config, group)
            try:
                if config.run_codex:
                    call_codex(config, token_key)
                if config.run_claude:
                    call_claude(config, token_key)
            finally:
                delete_smoke_token(config, token_id)

        if config.run_router_compat:
            call_router_compat_models(config)
    except SmokeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
