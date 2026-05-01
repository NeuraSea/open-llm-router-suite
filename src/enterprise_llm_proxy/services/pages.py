from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from enterprise_llm_proxy.config import AppSettings


def build_identity_provider_authorize_url(
    settings: AppSettings, *, state: str | None = None
) -> str | None:
    if settings.oidc_authorize_url and settings.oidc_client_id and settings.oidc_redirect_uri:
        query = {
            "client_id": settings.oidc_client_id,
            "redirect_uri": settings.oidc_redirect_uri,
            "response_type": "code",
            "scope": settings.oidc_scope,
        }
        if state:
            query["state"] = state
        return settings.oidc_authorize_url + "?" + urlencode(query)

    return build_feishu_authorize_url(settings, state=state)


def build_feishu_authorize_url(settings: AppSettings, *, state: str | None = None) -> str | None:
    if not settings.feishu_client_id or not settings.feishu_redirect_uri:
        return None

    query = {
        "client_id": settings.feishu_client_id,
        "redirect_uri": settings.feishu_redirect_uri,
        "response_type": "code",
        "scope": "contact:user.email:readonly",
    }
    if state:
        query["state"] = state
    return "https://accounts.feishu.cn/open-apis/authen/v1/authorize?" + urlencode(query)


def resolve_ui_dist_dir() -> Path | None:
    current = Path(__file__).resolve()
    candidates = [
        current.parents[1] / "static" / "ui",
        current.parents[3] / "web" / "dist",
    ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return None


def load_spa_index_html() -> str:
    dist_dir = resolve_ui_dist_dir()
    if dist_dir is None:
        return """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>企业级 LLM Router 控制台</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
"""

    return (dist_dir / "index.html").read_text(encoding="utf-8")
