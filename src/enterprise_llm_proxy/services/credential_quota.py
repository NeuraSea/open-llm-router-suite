"""Fetch quota/balance info from upstream provider APIs."""
from __future__ import annotations

import base64
import json as _json
from datetime import UTC, datetime, timedelta

import httpx

from enterprise_llm_proxy.services.claude_code_import import (
    claude_code_oauth_headers,
    extract_claude_code_available_models,
)

from enterprise_llm_proxy.domain.credentials import ProviderCredential


class QuotaFetchError(Exception):
    """Raised when the upstream provider returns an error or unexpected response."""


async def fetch_quota(credential: ProviderCredential) -> dict:
    """
    Return updated quota_info or billing_info dict.
    Raises QuotaFetchError with a human-readable message on failure.
    Raises ValueError if provider is not supported.
    """
    if credential.provider == "zhipu":
        return await _fetch_zhipu_balance(credential.access_token or "")
    if credential.provider == "minimax":
        return await _fetch_minimax_balance(credential.access_token or "")
    if credential.provider == "claude-max":
        return await _fetch_claude_max_quota(credential.access_token or "")
    if credential.provider == "openai-codex":
        return await _fetch_openai_codex_quota(credential.access_token or "")
    raise ValueError(f"Quota refresh not supported for provider '{credential.provider}'")


async def _fetch_zhipu_balance(api_key: str) -> dict:
    """
    ZhipuAI (Z-AI) user balance:
    GET https://open.bigmodel.cn/api/paas/v4/user/balance
    Authorization: Bearer {api_key}

    Successful response shape (as of 2025):
    {
      "code": 200,
      "data": {
        "credit_info": {
          "total_credit": "100.00",
          "used_credit": "10.00",
          "available_credit": "90.00"
        },
        "token_info": {
          "total_token": 0,
          "available_token": 0,
          "expire_time": ""
        }
      }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://open.bigmodel.cn/api/paas/v4/user/balance",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.RequestError as exc:
        raise QuotaFetchError(f"Network error calling ZhipuAI balance API: {exc}") from exc

    if resp.status_code != 200:
        raise QuotaFetchError(
            f"ZhipuAI balance API returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    try:
        body = resp.json()
    except Exception as exc:
        raise QuotaFetchError(f"ZhipuAI balance API returned non-JSON: {resp.text[:300]}") from exc

    data = body.get("data") or body
    credit = data.get("credit_info") or {}
    token = data.get("token_info") or {}

    available_credit = credit.get("available_credit") or credit.get("available_balance")
    total_credit = credit.get("total_credit") or credit.get("total_balance")
    available_token = token.get("available_token")
    total_token = token.get("total_token")
    expire_time = token.get("expire_time") or ""

    # subscription-style: token quota with expiry
    if total_token and int(total_token) > 0:
        used = int(total_token) - int(available_token or 0)
        used_pct = round(used / int(total_token) * 100)
        return {
            "windows": [{
                "label": "Token 配额",
                "used_pct": used_pct,
                "reset_at": expire_time,
            }]
        }

    # pay-per-use: credit balance
    if available_credit is not None:
        return {"balance_cny": float(available_credit)}

    raise QuotaFetchError(
        f"ZhipuAI balance API returned unexpected shape: {str(body)[:400]}"
    )


async def _fetch_minimax_balance(api_key: str) -> dict:
    """
    MiniMax account balance:
    GET https://api.minimax.chat/v1/account_balance
    Authorization: Bearer {api_key}
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.minimax.chat/v1/account_balance",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.RequestError as exc:
        raise QuotaFetchError(f"Network error calling MiniMax balance API: {exc}") from exc

    if resp.status_code != 200:
        raise QuotaFetchError(
            f"MiniMax balance API returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    try:
        data = resp.json()
    except Exception as exc:
        raise QuotaFetchError(f"MiniMax balance API returned non-JSON: {resp.text[:300]}") from exc

    balance = data.get("balance") or {}
    balance_cny = balance.get("balance") or balance.get("available_balance")
    if balance_cny is not None:
        return {"balance_cny": float(balance_cny)}

    raise QuotaFetchError(
        f"MiniMax balance API returned unexpected shape: {str(data)[:400]}"
    )


async def _fetch_claude_max_quota(access_token: str) -> dict:
    """
    Claude Max subscription quota via rate-limit headers on /v1/models.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers=claude_code_oauth_headers(access_token),
            )
    except httpx.RequestError as exc:
        raise QuotaFetchError(f"Network error calling Anthropic models API: {exc}") from exc

    if resp.status_code != 200:
        raise QuotaFetchError(
            f"Anthropic models API returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    try:
        payload = resp.json()
    except Exception:
        payload = None

    status_header = resp.headers.get("anthropic-ratelimit-unified-status")
    if not status_header:
        raise QuotaFetchError(
            f"anthropic-ratelimit-unified-status header not present. "
            f"Available headers: {list(resp.headers.keys())}"
        )

    try:
        status_data = _json.loads(status_header)
    except Exception as exc:
        raise QuotaFetchError(
            f"Failed to parse anthropic-ratelimit-unified-status header: {status_header[:300]}"
        ) from exc

    reset_header = resp.headers.get("anthropic-ratelimit-unified-reset")

    windows: list[dict] = []
    label_map = {
        "five_hour": "5小时配额",
        "seven_day": "7天配额",
    }

    if isinstance(status_data, dict):
        for key, label in label_map.items():
            window = status_data.get(key)
            if not isinstance(window, dict):
                continue
            used_pct = window.get("used_percentage", 0)
            resets_at = window.get("resets_at")
            reset_at_iso = ""
            if isinstance(resets_at, (int, float)):
                reset_at_iso = datetime.fromtimestamp(resets_at, tz=UTC).isoformat()
            elif isinstance(resets_at, str):
                reset_at_iso = resets_at
            windows.append({"label": label, "used_pct": used_pct, "reset_at": reset_at_iso})

    # Fallback: try to extract from any remaining top-level keys
    if not windows and isinstance(status_data, dict):
        for key, value in status_data.items():
            if not isinstance(value, dict):
                continue
            used_pct = value.get("used_percentage", 0)
            resets_at = value.get("resets_at")
            reset_at_iso = ""
            if isinstance(resets_at, (int, float)):
                reset_at_iso = datetime.fromtimestamp(resets_at, tz=UTC).isoformat()
            elif isinstance(resets_at, str):
                reset_at_iso = resets_at
            windows.append({"label": key, "used_pct": used_pct, "reset_at": reset_at_iso})

    if not windows:
        raise QuotaFetchError(
            f"Could not extract quota windows from header: {status_header[:400]}"
        )

    result = {"windows": windows}
    if isinstance(payload, dict):
        discovered = extract_claude_code_available_models(payload)
        if discovered:
            result["available_models"] = discovered

    return result


def _jwt_account_id(token: str) -> str | None:
    try:
        payload_b64 = token.split(".")[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        claims = _json.loads(base64.urlsafe_b64decode(payload_b64))
        return claims.get("chatgpt_account_id") or claims.get("account_id")
    except Exception:
        return None


async def _fetch_openai_codex_quota(access_token: str) -> dict:
    """
    OpenAI Codex subscription quota via ChatGPT backend API.
    """
    account_id = _jwt_account_id(access_token)

    headers: dict[str, str] = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://chatgpt.com/backend-api/codex/usage",
                headers=headers,
            )
    except httpx.RequestError as exc:
        raise QuotaFetchError(f"Network error calling Codex usage API: {exc}") from exc

    if resp.status_code != 200:
        raise QuotaFetchError(
            f"Codex usage API returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    try:
        body = resp.text
        data = _json.loads(body)
    except Exception as exc:
        raise QuotaFetchError(f"Codex usage API returned non-JSON: {resp.text[:300]}") from exc

    if not isinstance(data, dict):
        raise QuotaFetchError(f"Unexpected Codex usage response: {body[:400]}")

    # Try to find primary_window at top level or nested under "data"
    primary = data.get("primary_window") or (data.get("data") or {}).get("primary_window")

    windows: list[dict] = []

    if isinstance(primary, dict):
        limit_window = primary.get("limit_window_seconds", 0)
        reset_after = primary.get("reset_after_seconds", 0)
        limit_reached = primary.get("limit_reached", False)

        if limit_reached:
            used_pct = 100
        elif limit_window and limit_window > 0:
            used_pct = round((1 - reset_after / limit_window) * 100)
        else:
            used_pct = 0

        reset_at = (datetime.now(UTC) + timedelta(seconds=reset_after)).isoformat()
        windows.append({"label": "Codex 配额", "used_pct": used_pct, "reset_at": reset_at})

    # Additional rate limits
    additional = data.get("additional_rate_limits") or (data.get("data") or {}).get("additional_rate_limits") or []
    for entry in additional:
        if not isinstance(entry, dict):
            continue
        limit_window = entry.get("limit_window_seconds", 0)
        reset_after = entry.get("reset_after_seconds", 0)
        limit_reached = entry.get("limit_reached", False)
        label = entry.get("label", "附加配额")

        if limit_reached:
            used_pct = 100
        elif limit_window and limit_window > 0:
            used_pct = round((1 - reset_after / limit_window) * 100)
        else:
            used_pct = 0

        reset_at = (datetime.now(UTC) + timedelta(seconds=reset_after)).isoformat()
        windows.append({"label": label, "used_pct": used_pct, "reset_at": reset_at})

    if not windows:
        raise QuotaFetchError(f"Unexpected Codex usage response: {body[:400]}")

    return {"windows": windows}
