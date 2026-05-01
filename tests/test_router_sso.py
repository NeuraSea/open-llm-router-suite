from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from enterprise_llm_proxy.app import create_app
from enterprise_llm_proxy.config import AppSettings
from enterprise_llm_proxy.services.identity import OidcIdentity


class FakeOidcClient:
    def exchange_code(self, code: str) -> dict[str, str]:
        return {"access_token": code}

    def fetch_userinfo(self, access_token: str) -> OidcIdentity:
        return OidcIdentity(
            subject="u-admin" if access_token == "admin-code" else "u-member",
            email="admin@example.com" if access_token == "admin-code" else "member@example.com",
            name="Admin" if access_token == "admin-code" else "Member",
            team_ids=["platform"],
            role="admin" if access_token == "admin-code" else "member",
            avatar_url="https://sso.example/avatar.png",
        )


def rsa_key_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def build_client(
    private_key_pem: str | None,
    *,
    session_cookie_domain: str | None = None,
    sso_return_to_allowed_hosts: list[str] | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            settings=AppSettings(
                router_public_base_url="https://router.example.com/v1",
                feishu_client_id="cli_test_123",
                feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
                router_sso_private_key_pem=private_key_pem,
                router_sso_issuer="router-test",
                router_sso_audience="new-api",
                router_sso_assertion_ttl_seconds=120,
                session_cookie_secure=False,
                session_cookie_domain=session_cookie_domain,
                sso_return_to_allowed_hosts=sso_return_to_allowed_hosts or [],
            ),
            oidc_client=FakeOidcClient(),
        )
    )


def issue_token(client: TestClient, code: str = "member-code") -> str:
    return client.post("/auth/oidc/callback", json={"code": code}).json()["access_token"]


def test_sso_assertion_is_rs256_signed_and_capped_to_60s() -> None:
    private_key, public_key = rsa_key_pair()
    client = build_client(private_key)
    token = issue_token(client, "admin-code")

    response = client.get("/sso/assertion", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 204
    assertion = response.headers["x-router-sso-assertion"]
    claims = jwt.decode(
        assertion,
        public_key,
        algorithms=["RS256"],
        issuer="router-test",
        audience="new-api",
    )
    assert claims["sub"] == "u-admin"
    assert claims["email"] == "admin@example.com"
    assert claims["name"] == "Admin"
    assert claims["picture"] == "https://sso.example/avatar.png"
    assert claims["avatar_url"] == "https://sso.example/avatar.png"
    assert claims["role"] == "admin"
    assert 0 < claims["exp"] - claims["iat"] <= 60


def test_sso_assertion_requires_private_key() -> None:
    client = build_client(None)
    token = issue_token(client)

    response = client.get("/sso/assertion", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Router SSO private key is not configured"


def test_sso_login_callback_sets_session_cookie_and_sanitizes_return_to() -> None:
    private_key, _ = rsa_key_pair()
    client = build_client(private_key)

    login = client.get(
        "/sso/login?return_to=https://evil.example/new-api",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/auth/oidc/callback?code=member-code&state={state}",
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert callback.headers["location"] == "/"
    assert "router_session=" in callback.headers["set-cookie"]


def test_sso_login_uses_router_sso_oidc_instead_of_legacy_feishu_oauth() -> None:
    private_key, _ = rsa_key_pair()
    client = TestClient(
        create_app(
            settings=AppSettings(
                router_public_base_url="https://router.example.com/v1",
                feishu_client_id="legacy_feishu_client",
                feishu_redirect_uri="https://router.example.com/auth/oidc/callback",
                oidc_authorize_url="https://sso.example.com/login/oauth/authorize",
                oidc_client_id="router",
                oidc_redirect_uri="https://newapi.example.com/auth/oidc/callback",
                oidc_scope="openid profile email offline_access",
                router_sso_private_key_pem=private_key,
                session_cookie_secure=False,
                sso_return_to_allowed_hosts=["newapi.example.com"],
            ),
            oidc_client=FakeOidcClient(),
        )
    )

    response = client.get(
        "/sso/login?return_to=https://newapi.example.com/",
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://sso.example.com/login/oauth/authorize"
    )
    assert query["client_id"] == ["router"]
    assert query["redirect_uri"] == ["https://newapi.example.com/auth/oidc/callback"]
    assert query["scope"] == ["openid profile email offline_access"]
    assert query["state"][0].startswith("sso:")
    assert "legacy_feishu_client" not in location
    assert "router.example.com%2Fauth%2Foidc%2Fcallback" not in location


def test_sso_login_callback_can_set_shared_parent_domain_cookie() -> None:
    private_key, _ = rsa_key_pair()
    client = build_client(
        private_key,
        session_cookie_domain=".example.com",
        sso_return_to_allowed_hosts=["newapi.example.com"],
    )

    login = client.get(
        "/sso/login?return_to=https://newapi.example.com/",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/auth/oidc/callback?code=member-code&state={state}",
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert callback.headers["location"] == "https://newapi.example.com/"
    assert "Domain=.example.com" in callback.headers["set-cookie"]


def test_sso_login_keeps_same_host_return_to() -> None:
    private_key, _ = rsa_key_pair()
    client = build_client(private_key)

    login = client.get(
        "/sso/login?return_to=https://router.example.com/api/channel",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/auth/oidc/callback?code=member-code&state={state}",
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert callback.headers["location"] == "https://router.example.com/api/channel"
