#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="${ROOT_DIR}/infra/kubernetes/lingtai-ai/lingtai-ai.yaml"
NAMESPACE="lingtai-ai"
CF_API_BASE="https://api.cloudflare.com/client/v4"
LINGTAI_ZONE="lingtai.ai"
API_HOST="api.lingtai.ai"
SSO_HOST="sso.lingtai.ai"
REFERENCE_ZONE="${REFERENCE_ZONE:-singularity-x.ai}"
REFERENCE_HOST="${REFERENCE_HOST:-api-new.singularity-x.ai}"
TUNNEL_NAME="${TUNNEL_NAME:-lingtai-api}"

require() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

rand_b64() {
  openssl rand -base64 36 | tr -d '\n'
}

rand_password() {
  openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 20
}

secret_exists() {
  kubectl -n "$1" get secret "$2" >/dev/null 2>&1
}

apply_secret_literal() {
  local namespace="$1"
  local name="$2"
  shift 2
  kubectl -n "$namespace" create secret generic "$name" "$@" --dry-run=client -o yaml | kubectl apply -f -
}

create_secret_if_missing() {
  local namespace="$1"
  local name="$2"
  shift 2
  if secret_exists "$namespace" "$name"; then
    printf 'secret/%s already exists in %s; preserving it\n' "$name" "$namespace"
    return
  fi
  apply_secret_literal "$namespace" "$name" "$@"
}

cf_request() {
  cf_request_with_token "${CF_NEWAPI_DEPLOY_OPS_TOKEN}" "$@"
}

cf_request_with_token() {
  local token="$1"
  shift
  local method="$1"
  local path="$2"
  local data="${3:-}"
  if [ -n "$data" ]; then
    curl -sS --max-time 30 -X "$method" \
      -H "Authorization: Bearer ${token}" \
      -H "Content-Type: application/json" \
      --data "$data" \
      "${CF_API_BASE}${path}"
  else
    curl -sS --max-time 30 -X "$method" \
      -H "Authorization: Bearer ${token}" \
      "${CF_API_BASE}${path}"
  fi
}

upsert_dns_record() {
  local zone_id="$1"
  local name="$2"
  local type="$3"
  local content="$4"
  local existing_id
  existing_id="$(cf_request GET "/zones/${zone_id}/dns_records?name=${name}" | jq -r '.result[0].id // empty')"
  local payload
  payload="$(jq -n --arg type "$type" --arg name "$name" --arg content "$content" \
    '{type:$type,name:$name,content:$content,ttl:1,proxied:true}')"
  if [ -n "$existing_id" ]; then
    cf_request PUT "/zones/${zone_id}/dns_records/${existing_id}" "$payload" | jq -e '.success == true' >/dev/null
    printf 'updated DNS %s %s -> %s (proxied)\n' "$type" "$name" "$content"
  else
    cf_request POST "/zones/${zone_id}/dns_records" "$payload" | jq -e '.success == true' >/dev/null
    printf 'created DNS %s %s -> %s (proxied)\n' "$type" "$name" "$content"
  fi
}

detect_origin_ip() {
  for url in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do
    local ip
    ip="$(curl -sS --noproxy '*' --max-time 10 "$url" 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ "$ip" =~ ^[0-9]+(\.[0-9]+){3}$ ]]; then
      printf '%s' "$ip"
      return
    fi
  done
  return 1
}

detect_reference_origin() {
  if [ -n "${LINGTAI_ORIGIN_CNAME:-}" ]; then
    printf 'CNAME %s\n' "${LINGTAI_ORIGIN_CNAME}"
    return
  fi
  if [ -n "${LINGTAI_ORIGIN_IP:-}" ]; then
    printf 'A %s\n' "${LINGTAI_ORIGIN_IP}"
    return
  fi

  if [ -n "${CLOUDFLARE_API_TOKEN:-}" ]; then
    local reference_zone_id
    reference_zone_id="$(cf_request_with_token "${CLOUDFLARE_API_TOKEN}" GET "/zones?name=${REFERENCE_ZONE}" | jq -r '.result[0].id // empty')"
    if [ -n "$reference_zone_id" ]; then
      local record
      record="$(cf_request_with_token "${CLOUDFLARE_API_TOKEN}" GET "/zones/${reference_zone_id}/dns_records?name=${REFERENCE_HOST}")"
      local record_type
      local record_content
      record_type="$(jq -r '.result[0].type // empty' <<<"$record")"
      record_content="$(jq -r '.result[0].content // empty' <<<"$record")"
      if [ "$record_type" = "CNAME" ] && [ -n "$record_content" ]; then
        printf 'CNAME %s\n' "$record_content"
        return
      fi
      if [ "$record_type" = "A" ] && [ -n "$record_content" ]; then
        printf 'A %s\n' "$record_content"
        return
      fi
    fi
  fi

  local origin_ip
  origin_ip="$(detect_origin_ip)"
  if [ -n "$origin_ip" ]; then
    printf 'A %s\n' "$origin_ip"
    return
  fi

  return 1
}

get_or_create_tunnel() {
  local account_id="$1"
  local tunnels
  tunnels="$(cf_request GET "/accounts/${account_id}/cfd_tunnel?name=${TUNNEL_NAME}")"
  local tunnel_id
  tunnel_id="$(jq -r --arg name "$TUNNEL_NAME" 'first(.result[]? | select(.name == $name and (.deleted_at == null)) | .id) // empty' <<<"$tunnels")"
  if [ -n "$tunnel_id" ]; then
    printf '%s\n' "$tunnel_id"
    return
  fi

  local payload
  payload="$(jq -n --arg name "$TUNNEL_NAME" '{name:$name,config_src:"cloudflare"}')"
  cf_request POST "/accounts/${account_id}/cfd_tunnel" "$payload" | jq -er '.result.id'
}

get_tunnel_token() {
  local account_id="$1"
  local tunnel_id="$2"
  cf_request GET "/accounts/${account_id}/cfd_tunnel/${tunnel_id}/token" | jq -er '.result'
}

configure_tunnel() {
  local account_id="$1"
  local tunnel_id="$2"
  local api_service="http://lingtai-api-gateway.${NAMESPACE}.svc.cluster.local:8080"
  local sso_service="http://lingtai-casdoor.${NAMESPACE}.svc.cluster.local:8000"
  local payload
  payload="$(
    jq -n \
      --arg api_host "$API_HOST" \
      --arg sso_host "$SSO_HOST" \
      --arg api_service "$api_service" \
      --arg sso_service "$sso_service" \
      '{
        config: {
          ingress: [
            {hostname: $api_host, service: $api_service, originRequest: {}},
            {hostname: $sso_host, service: $sso_service, originRequest: {}},
            {service: "http_status:404", originRequest: {}}
          ]
        }
      }'
  )"
  cf_request PUT "/accounts/${account_id}/cfd_tunnel/${tunnel_id}/configurations" "$payload" | jq -e '.success == true' >/dev/null
}

seed_casdoor() {
  local oidc_client_secret
  local bootstrap_admin_username
  local bootstrap_admin_password
  local bootstrap_admin_password_hash
  local bootstrap_admin_id
  oidc_client_secret="$(kubectl -n "$NAMESPACE" get secret lingtai-router-app -o jsonpath='{.data.ENTERPRISE_LLM_PROXY_OIDC_CLIENT_SECRET}' | base64 -d)"
  bootstrap_admin_username="$(kubectl -n "$NAMESPACE" get secret lingtai-casdoor-bootstrap-admin -o jsonpath='{.data.username}' | base64 -d)"
  bootstrap_admin_password="$(kubectl -n "$NAMESPACE" get secret lingtai-casdoor-bootstrap-admin -o jsonpath='{.data.password}' | base64 -d)"
  bootstrap_admin_password_hash="$(htpasswd -bnBC 10 '' "$bootstrap_admin_password" | tr -d ':\n')"
  bootstrap_admin_password_hash="${bootstrap_admin_password_hash/\$2y\$/\$2a\$}"
  bootstrap_admin_id="$(uuidgen | tr '[:upper:]' '[:lower:]')"

  kubectl -n "$NAMESPACE" exec -i statefulset/lingtai-casdoor-postgresql -- \
    psql -q -U casdoor -d casdoor \
      -v ON_ERROR_STOP=1 \
      -v oidc_client_secret="$oidc_client_secret" \
      -v bootstrap_admin_username="$bootstrap_admin_username" \
      -v bootstrap_admin_password_hash="$bootstrap_admin_password_hash" \
      -v bootstrap_admin_id="$bootstrap_admin_id" \
      -v wechat_app_id="${LINGTAI_WECHAT_APP_ID:-}" \
      -v wechat_app_secret="${LINGTAI_WECHAT_APP_SECRET:-}" <<'SQL'
CREATE TEMP TABLE seed_vars (
  oidc_client_secret text,
  bootstrap_admin_username text,
  bootstrap_admin_password_hash text,
  bootstrap_admin_id text,
  wechat_app_id text,
  wechat_app_secret text
);
INSERT INTO seed_vars VALUES (
  :'oidc_client_secret',
  :'bootstrap_admin_username',
  :'bootstrap_admin_password_hash',
  :'bootstrap_admin_id',
  :'wechat_app_id',
  :'wechat_app_secret'
);

DO $$
DECLARE
  now_text text := to_char(now() at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
  oidc_secret text;
  bootstrap_admin_username text;
  bootstrap_admin_password_hash text;
  bootstrap_admin_id text;
  wechat_id text;
  wechat_secret text;
  scope_items text := jsonb_build_array(
    jsonb_build_object('name', 'openid', 'displayName', 'OpenID', 'description', 'OpenID Connect scope', 'tools', jsonb_build_array()),
    jsonb_build_object('name', 'profile', 'displayName', 'Profile', 'description', 'Basic profile information', 'tools', jsonb_build_array()),
    jsonb_build_object('name', 'email', 'displayName', 'Email', 'description', 'Email address', 'tools', jsonb_build_array()),
    jsonb_build_object('name', 'offline_access', 'displayName', 'Offline Access', 'description', 'Refresh token access', 'tools', jsonb_build_array())
  )::text;
  provider_refs text := '[]';
  signin_method_refs text := jsonb_build_array(
    jsonb_build_object('name', 'Password', 'displayName', 'Password', 'rule', 'All')
  )::text;
BEGIN
  SELECT
    seed_vars.oidc_client_secret,
    seed_vars.bootstrap_admin_username,
    seed_vars.bootstrap_admin_password_hash,
    seed_vars.bootstrap_admin_id,
    seed_vars.wechat_app_id,
    seed_vars.wechat_app_secret
    INTO
      oidc_secret,
      bootstrap_admin_username,
      bootstrap_admin_password_hash,
      bootstrap_admin_id,
      wechat_id,
      wechat_secret
    FROM seed_vars
    LIMIT 1;

  INSERT INTO organization
  SELECT (json_populate_record(NULL::organization, (
    row_to_json(o)::jsonb || jsonb_build_object(
      'owner', 'admin',
      'name', 'lingtai',
      'created_time', now_text,
      'display_name', 'Lingtai',
      'website_url', 'https://api.lingtai.ai',
      'default_application', 'api-lingtai'
    )
  )::json)).*
  FROM organization o
  WHERE o.owner = 'admin' AND o.name = 'built-in'
  ON CONFLICT (owner, name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    website_url = EXCLUDED.website_url,
    default_application = EXCLUDED.default_application;

  IF wechat_id <> '' AND wechat_secret <> '' THEN
    provider_refs := jsonb_build_array(
      jsonb_build_object(
        'owner', 'admin',
        'name', 'provider_wechat_lingtai_web',
        'canSignUp', true,
        'canSignIn', true,
        'canUnlink', false,
        'bindingRule', null,
        'countryCodes', null,
        'prompted', false,
        'signupGroup', '',
        'rule', 'All',
        'provider', null
      )
    )::text;
    signin_method_refs := (
      signin_method_refs::jsonb || jsonb_build_array(
        jsonb_build_object('name', 'WeChat', 'displayName', 'WeChat', 'rule', 'All')
      )
    )::text;

    INSERT INTO provider (
      owner, name, created_time, display_name, category, type, sub_type, method,
      client_id, client_secret, client_id2, client_secret2, scopes, provider_url,
      enable_proxy, enable_pkce, state
    ) VALUES (
      'admin', 'provider_wechat_lingtai_web', now_text, 'WeChat Web', 'OAuth', 'WeChat', 'Web', 'Normal',
      wechat_id, wechat_secret, '', '', 'snsapi_login', '', false, false, ''
    )
    ON CONFLICT (owner, name) DO UPDATE SET
      display_name = EXCLUDED.display_name,
      category = EXCLUDED.category,
      type = EXCLUDED.type,
      sub_type = EXCLUDED.sub_type,
      method = EXCLUDED.method,
      client_id = EXCLUDED.client_id,
      client_secret = EXCLUDED.client_secret,
      scopes = EXCLUDED.scopes;
  END IF;

  INSERT INTO application
  SELECT (json_populate_record(NULL::application, (
    row_to_json(a)::jsonb || jsonb_build_object(
      'owner', 'admin',
      'name', 'api-lingtai',
      'created_time', now_text,
      'display_name', 'Lingtai API',
      'category', 'Default',
      'type', 'All',
      'scopes', scope_items,
      'logo', 'https://sso.lingtai.ai/favicon.png',
      'homepage_url', 'https://api.lingtai.ai',
      'description', 'Lingtai API Router and New API SSO',
      'organization', 'lingtai',
      'enable_password', true,
      'enable_sign_up', true,
      'enable_guest_signin', false,
      'disable_signin', false,
      'providers', provider_refs,
      'signin_methods', signin_method_refs,
      'grant_types', '["authorization_code","refresh_token"]',
      'client_id', 'api-lingtai',
      'client_secret', oidc_secret,
      'redirect_uris', '["https://api.lingtai.ai/auth/oidc/callback"]',
      'token_format', 'JWT',
      'expire_in_hours', 8,
      'refresh_expire_in_hours', 168,
      'cookie_expire_in_hours', 8,
      'domain', 'api.lingtai.ai',
      'other_domains', '["api.lingtai.ai"]'
    )
  )::json)).*
  FROM application a
  WHERE a.owner = 'admin' AND a.name = 'app-built-in'
  ON CONFLICT (owner, name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    scopes = EXCLUDED.scopes,
    homepage_url = EXCLUDED.homepage_url,
    description = EXCLUDED.description,
    organization = EXCLUDED.organization,
    enable_password = EXCLUDED.enable_password,
    enable_sign_up = EXCLUDED.enable_sign_up,
    providers = EXCLUDED.providers,
    signin_methods = EXCLUDED.signin_methods,
    grant_types = EXCLUDED.grant_types,
    client_id = EXCLUDED.client_id,
    client_secret = EXCLUDED.client_secret,
    redirect_uris = EXCLUDED.redirect_uris,
    token_format = EXCLUDED.token_format,
    expire_in_hours = EXCLUDED.expire_in_hours,
    refresh_expire_in_hours = EXCLUDED.refresh_expire_in_hours,
    cookie_expire_in_hours = EXCLUDED.cookie_expire_in_hours,
    domain = EXCLUDED.domain,
    other_domains = EXCLUDED.other_domains;

  INSERT INTO "user"
  SELECT (json_populate_record(NULL::"user", (
    row_to_json(u)::jsonb || jsonb_build_object(
      'owner', 'lingtai',
      'name', bootstrap_admin_username,
      'created_time', now_text,
      'updated_time', now_text,
      'deleted_time', '',
      'id', bootstrap_admin_id,
      'password', bootstrap_admin_password_hash,
      'password_salt', '',
      'password_type', 'bcrypt',
      'display_name', 'Lingtai Admin',
      'email', 'admin@lingtai.ai',
      'email_verified', true,
      'phone', '',
      'is_admin', true,
      'is_forbidden', false,
      'is_deleted', false,
      'signup_application', 'api-lingtai',
      'register_type', 'manual',
      'register_source', 'seed',
      'hash', '',
      'pre_hash', '',
      'groups', '[]',
      'application_scopes', '[]'
    )
  )::json)).*
  FROM "user" u
  WHERE u.owner = 'built-in' AND u.name = 'admin'
    AND NOT EXISTS (
      SELECT 1 FROM "user" existing
      WHERE existing.owner = 'lingtai' AND existing.name = bootstrap_admin_username
    );
END $$;

DROP TABLE seed_vars;
SQL
  printf 'seeded Casdoor organization/application/bootstrap admin for %s\n' "$API_HOST"
}

require kubectl
require curl
require jq
require openssl
require htpasswd

: "${CF_CERT_MANAGER_DNS01_TOKEN:?set CF_CERT_MANAGER_DNS01_TOKEN}"
: "${CF_NEWAPI_DEPLOY_OPS_TOKEN:?set CF_NEWAPI_DEPLOY_OPS_TOKEN}"

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

apply_secret_literal cert-manager cloudflare-lingtai-api-token \
  --from-literal=api-token="${CF_CERT_MANAGER_DNS01_TOKEN}"

create_secret_if_missing "$NAMESPACE" lingtai-router-postgres \
  --from-literal=password="$(rand_b64)"
create_secret_if_missing "$NAMESPACE" lingtai-newapi-postgres \
  --from-literal=password="$(rand_b64)"
create_secret_if_missing "$NAMESPACE" lingtai-casdoor-postgres \
  --from-literal=password="$(rand_b64)"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
if ! secret_exists "$NAMESPACE" lingtai-router-app || ! secret_exists "$NAMESPACE" lingtai-new-api; then
  openssl genrsa -out "$tmpdir/router-sso-private.pem" 2048 >/dev/null 2>&1
  openssl rsa -in "$tmpdir/router-sso-private.pem" -pubout -out "$tmpdir/router-sso-public.pem" >/dev/null 2>&1
fi

if ! secret_exists "$NAMESPACE" lingtai-router-app; then
  create_secret_if_missing "$NAMESPACE" lingtai-router-app \
    --from-literal=ENTERPRISE_LLM_PROXY_JWT_SIGNING_SECRET="$(rand_b64)" \
    --from-literal=ENTERPRISE_LLM_PROXY_ROUTER_SSO_PRIVATE_KEY_PEM="$(cat "$tmpdir/router-sso-private.pem")" \
    --from-literal=ENTERPRISE_LLM_PROXY_OIDC_CLIENT_SECRET="$(rand_b64)" \
    --from-literal=ENTERPRISE_LLM_PROXY_BRIDGE_UPSTREAM_API_KEY="$(rand_b64)" \
    --from-literal=ENTERPRISE_LLM_PROXY_NEWAPI_ADMIN_ACCESS_TOKEN="__SET_AFTER_NEWAPI_SETUP__"
fi

if ! secret_exists "$NAMESPACE" lingtai-new-api; then
  create_secret_if_missing "$NAMESPACE" lingtai-new-api \
    --from-literal=session-secret="$(rand_b64)" \
    --from-literal=router-sso-public-key-pem="$(cat "$tmpdir/router-sso-public.pem")"
fi

if ! secret_exists "$NAMESPACE" lingtai-casdoor; then
  casdoor_db_password="$(kubectl -n "$NAMESPACE" get secret lingtai-casdoor-postgres -o jsonpath='{.data.password}' | base64 -d)"
  create_secret_if_missing "$NAMESPACE" lingtai-casdoor \
    --from-literal=dataSourceName="user=casdoor password=${casdoor_db_password} host=lingtai-casdoor-postgresql port=5432 sslmode=disable dbname=casdoor"
fi

create_secret_if_missing "$NAMESPACE" lingtai-casdoor-bootstrap-admin \
  --from-literal=username="admin" \
  --from-literal=password="$(rand_password)"

zone_payload="$(cf_request GET "/zones?name=${LINGTAI_ZONE}")"
zone_id="$(jq -r '.result[0].id // empty' <<<"$zone_payload")"
if [ -z "$zone_id" ]; then
  printf 'Cloudflare zone not visible: %s\n' "$LINGTAI_ZONE" >&2
  exit 1
fi
account_id="$(jq -r '.result[0].account.id // empty' <<<"$zone_payload")"

if [ -n "$account_id" ]; then
  tunnel_id="$(get_or_create_tunnel "$account_id")"
  configure_tunnel "$account_id" "$tunnel_id"
  tunnel_token="$(get_tunnel_token "$account_id" "$tunnel_id")"
  apply_secret_literal "$NAMESPACE" lingtai-cloudflared \
    --from-literal=TUNNEL_TOKEN="${tunnel_token}"
  ORIGIN_TYPE="CNAME"
  ORIGIN_VALUE="${tunnel_id}.cfargotunnel.com"
else
  read -r ORIGIN_TYPE ORIGIN_VALUE < <(detect_reference_origin)
fi

if [ -z "${ORIGIN_TYPE:-}" ] || [ -z "${ORIGIN_VALUE:-}" ]; then
  printf 'could not detect origin; set LINGTAI_ORIGIN_CNAME or LINGTAI_ORIGIN_IP\n' >&2
  exit 1
fi

upsert_dns_record "$zone_id" "$API_HOST" "$ORIGIN_TYPE" "$ORIGIN_VALUE"
upsert_dns_record "$zone_id" "$SSO_HOST" "$ORIGIN_TYPE" "$ORIGIN_VALUE"

kubectl apply -f "$MANIFEST"
kubectl -n "$NAMESPACE" rollout status statefulset/lingtai-casdoor-postgresql --timeout=120s >/dev/null
seed_casdoor

cat <<EOF
Lingtai resources applied.

Origin ${ORIGIN_TYPE}: ${ORIGIN_VALUE}
Tunnel name: ${TUNNEL_NAME}
Namespace: ${NAMESPACE}
Casdoor: https://${SSO_HOST}
API/New API gateway: https://${API_HOST}

Casdoor seeded:
- Organization: lingtai
- Application: api-lingtai
- Password sign-in: enabled
- Redirect URL: https://${API_HOST}/auth/oidc/callback
- Bootstrap admin secret:
  kubectl -n ${NAMESPACE} get secret lingtai-casdoor-bootstrap-admin -o jsonpath='{.data.username}' | base64 -d
  kubectl -n ${NAMESPACE} get secret lingtai-casdoor-bootstrap-admin -o jsonpath='{.data.password}' | base64 -d

Remaining required configuration:
- Rerun with LINGTAI_WECHAT_APP_ID and LINGTAI_WECHAT_APP_SECRET to populate real WeChat credentials.
- After New API admin setup, replace ENTERPRISE_LLM_PROXY_NEWAPI_ADMIN_ACCESS_TOKEN and set NEWAPI_SYNC_ENABLED=true.
EOF
