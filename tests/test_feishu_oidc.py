import httpx

from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.services.feishu import FeishuOidcClient


def test_feishu_oidc_client_maps_code_exchange_and_user_info() -> None:
    seen_requests: list[tuple[str, str, dict[str, str] | None, dict[str, str] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        json_body = None
        if request.content:
            import json

            json_body = json.loads(request.content.decode("utf-8"))
        seen_requests.append(
            (
                request.method,
                request.url.path,
                dict(request.headers),
                json_body,
            )
        )

        if request.url.path == "/authen/v2/oauth/token":
            return httpx.Response(200, json={"access_token": "feishu-user-token"})
        if request.url.path == "/user_info":
            return httpx.Response(
                200,
                json={
                    "open_id": "ou_member",
                    "name": "Alice",
                    "email": "alice@example.com",
                    "department_ids": ["platform"],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    transport = httpx.MockTransport(handler)
    settings = AppSettings(
        feishu_client_id="cli_123",
        feishu_client_secret="secret",
        feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
        feishu_token_url="https://feishu.example.com/authen/v2/oauth/token",
        feishu_userinfo_url="https://feishu.example.com/user_info",
    )
    client = FeishuOidcClient(settings=settings, http_client=httpx.Client(transport=transport))

    token_payload = client.exchange_code("auth-code")
    identity = client.fetch_userinfo(str(token_payload["access_token"]))

    assert token_payload["access_token"] == "feishu-user-token"
    assert identity.subject == "ou_member"
    assert identity.email == "alice@example.com"
    assert identity.team_ids == ["platform"]
    assert seen_requests[0][1] == "/authen/v2/oauth/token"
    assert "authorization" not in seen_requests[0][2]
    assert seen_requests[0][3] == {
        "grant_type": "authorization_code",
        "code": "auth-code",
        "client_id": "cli_123",
        "client_secret": "secret",
        "redirect_uri": "https://router.example.com/auth/oidc/callback",
    }
    assert seen_requests[1][1] == "/user_info"


def test_feishu_oidc_client_marks_admin_when_subject_is_whitelisted_without_email() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/authen/v2/oauth/token":
            return httpx.Response(200, json={"access_token": "feishu-user-token"})
        if request.url.path == "/user_info":
            return httpx.Response(
                200,
                json={
                    "open_id": "ou_97abfe09aaf1004b8ad5b7c37700a337",
                    "name": "田闰心",
                    "department_ids": ["default"],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    transport = httpx.MockTransport(handler)
    settings = AppSettings(
        feishu_client_id="cli_123",
        feishu_client_secret="secret",
        feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
        feishu_token_url="https://feishu.example.com/authen/v2/oauth/token",
        feishu_userinfo_url="https://feishu.example.com/user_info",
        admin_subjects=["ou_97abfe09aaf1004b8ad5b7c37700a337"],
    )
    client = FeishuOidcClient(settings=settings, http_client=httpx.Client(transport=transport))

    token_payload = client.exchange_code("auth-code")
    identity = client.fetch_userinfo(str(token_payload["access_token"]))

    assert identity.subject == "ou_97abfe09aaf1004b8ad5b7c37700a337"
    assert identity.email == ""
    assert identity.role == "admin"
