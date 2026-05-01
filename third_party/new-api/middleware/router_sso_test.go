package middleware

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func testRouterSSOKeyPair(t *testing.T) (*rsa.PrivateKey, string) {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("generate rsa key: %v", err)
	}
	publicBytes, err := x509.MarshalPKIXPublicKey(&key.PublicKey)
	if err != nil {
		t.Fatalf("marshal public key: %v", err)
	}
	publicPEM := string(pem.EncodeToMemory(&pem.Block{
		Type:  "PUBLIC KEY",
		Bytes: publicBytes,
	}))
	return key, publicPEM
}

func signRouterSSOTestJWT(t *testing.T, key *rsa.PrivateKey, claims jwt.MapClaims) string {
	t.Helper()
	token, err := jwt.NewWithClaims(jwt.SigningMethodRS256, claims).SignedString(key)
	if err != nil {
		t.Fatalf("sign jwt: %v", err)
	}
	return token
}

func TestVerifyRouterSSOAssertionValidatesRS256Claims(t *testing.T) {
	key, publicPEM := testRouterSSOKeyPair(t)
	t.Setenv("ROUTER_SSO_PUBLIC_KEY_PEM", publicPEM)
	t.Setenv("ROUTER_SSO_ISSUER", "router-test")
	t.Setenv("ROUTER_SSO_AUDIENCE", "new-api")

	now := time.Now()
	assertion := signRouterSSOTestJWT(t, key, jwt.MapClaims{
		"iss":   "router-test",
		"aud":   "new-api",
		"sub":   "u-123",
		"email": "member@example.com",
		"name":  "Member",
		"role":  "admin",
		"iat":   now.Unix(),
		"exp":   now.Add(time.Minute).Unix(),
	})

	claims, err := verifyRouterSSOAssertion(assertion)

	if err != nil {
		t.Fatalf("verify assertion: %v", err)
	}
	if claims.Sub != "u-123" {
		t.Fatalf("sub: got %q", claims.Sub)
	}
	if claims.Role != "admin" {
		t.Fatalf("role: got %q", claims.Role)
	}
}

func TestVerifyRouterSSOAssertionReadsAvatarClaims(t *testing.T) {
	key, publicPEM := testRouterSSOKeyPair(t)
	t.Setenv("ROUTER_SSO_PUBLIC_KEY_PEM", publicPEM)
	t.Setenv("ROUTER_SSO_AUDIENCE", "new-api")

	assertion := signRouterSSOTestJWT(t, key, jwt.MapClaims{
		"aud":        "new-api",
		"sub":        "u-123",
		"avatar_url": "https://sso.example/avatar.png",
		"exp":        time.Now().Add(time.Minute).Unix(),
	})

	claims, err := verifyRouterSSOAssertion(assertion)

	if err != nil {
		t.Fatalf("verify assertion: %v", err)
	}
	if claims.Picture != "https://sso.example/avatar.png" {
		t.Fatalf("picture: got %q", claims.Picture)
	}
}

func TestRouterSSOPrivateGroupUsesStableSubject(t *testing.T) {
	got := routerSSOPrivateGroup("ou_fa0b9f86f1162800d8e8c2aa3c8dfe3f")
	want := "private-ou_fa0b9f86f1162800d8e8c2aa3c8dfe3f"

	if got != want {
		t.Fatalf("group: got %q, want %q", got, want)
	}
}

func TestVerifyRouterSSOAssertionRejectsWrongAudience(t *testing.T) {
	key, publicPEM := testRouterSSOKeyPair(t)
	t.Setenv("ROUTER_SSO_PUBLIC_KEY_PEM", publicPEM)
	t.Setenv("ROUTER_SSO_AUDIENCE", "new-api")

	assertion := signRouterSSOTestJWT(t, key, jwt.MapClaims{
		"aud": "other-api",
		"sub": "u-123",
		"exp": time.Now().Add(time.Minute).Unix(),
	})

	if _, err := verifyRouterSSOAssertion(assertion); err == nil {
		t.Fatal("expected wrong audience to be rejected")
	}
}
