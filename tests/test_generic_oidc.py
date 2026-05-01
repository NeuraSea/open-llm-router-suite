import httpx

from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.services.oidc import GenericOidcClient


def test_generic_oidc_client_exchanges_code_with_form_encoded_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/access_token"):
            return httpx.Response(200, json={"access_token": "sso-token"})
        return httpx.Response(
            200,
            json={
                "sub": "user-1",
                "email": "member@example.com",
                "name": "Member",
                "groups": ["platform"],
            },
        )

    client = GenericOidcClient(
        settings=AppSettings(
            oidc_client_id="router",
            oidc_client_secret="secret",
            oidc_redirect_uri="https://newapi.example.com/auth/oidc/callback",
            oidc_token_url="https://sso.example.com/api/login/oauth/access_token",
            oidc_userinfo_url="https://sso.example.com/api/userinfo",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    token = client.exchange_code("code-1")
    identity = client.fetch_userinfo(token["access_token"])

    assert token == {"access_token": "sso-token"}
    assert identity.subject == "user-1"
    assert identity.email == "member@example.com"
    assert identity.team_ids == ["platform"]
    token_request = requests[0]
    assert token_request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert token_request.content.decode() == (
        "grant_type=authorization_code&code=code-1&client_id=router&"
        "client_secret=secret&redirect_uri=https%3A%2F%2Fnewapi.example.com"
        "%2Fauth%2Foidc%2Fcallback"
    )
