# new-api + Router SSO Smoke Runbook

This runbook is for Lane 3 end-to-end smoke on the current split deployment:

- Parent repo owns Router SSO, OIDC callback, `oauth-bridge`, and `routerctl`
- `third_party/new-api` owns UI, channels, tokens, gateway, logs, audit, and usage
- `nginx` fronts both and protects `new-api` UI/API with `auth_request /_sso_assertion`

Use placeholders only. Do not paste secrets into this file, shell history you intend to keep, or git-tracked files.

## 1. Variables

Set these before running the smoke:

```bash
export ROUTER_BASE_URL="https://router.example.com"
export ROUTER_HOST="router.example.com"
export NEWAPI_BASE_URL="$ROUTER_BASE_URL"
export ROUTERCTL_SESSION_FILE="${HOME}/.enterprise-llm-proxy/session.json"

export ENTERPRISE_GROUP="<router-sso-enterprise-group>"
export NEWAPI_ADMIN_ACCESS_TOKEN="<new-api-admin-access-token>"
export NEWAPI_ADMIN_USER_ID="<new-api-admin-user-id>"

# After browser SSO succeeds, copy the new-api `session` cookie from DevTools.
export NEWAPI_SESSION_COOKIE="<browser-session-cookie>"
```

Expected outcomes:

- `ROUTER_BASE_URL` is the public HTTPS origin fronted by `nginx`
- `NEWAPI_BASE_URL` stays the same origin because `/`, `/api/*`, `/usage-logs/*`, and `/v1/*` are same-origin behind `nginx`
- `NEWAPI_SESSION_COOKIE` is the `session` cookie issued by `new-api`, not the router bearer token

## 2. Bring Up the Stack

From the repo root:

```bash
docker compose --env-file .env.local up -d --build
docker compose --env-file .env.local ps
```

Expected outcomes:

- `postgres`, `newapi-postgres`, `app`, `new-api`, and `nginx` are `Up`
- both Postgres containers report healthy

Quick preflight:

```bash
curl -skI "https://${ROUTER_HOST}/" | sed -n '1,8p'
```

Expected outcomes:

- unauthenticated requests return `302` or `303`
- `Location` points at `/sso/login?...`

Triage:

- if `nginx` is down, run `docker compose --env-file .env.local logs nginx --tail=200`
- if `app` or `new-api` is unhealthy, run `docker compose --env-file .env.local logs app new-api --tail=200`
- if `/_sso_assertion` returns 503, check `ENTERPRISE_LLM_PROXY_ROUTER_SSO_PRIVATE_KEY_PEM` and `ROUTER_SSO_PUBLIC_KEY_PEM`

## 3. Browser SSO Smoke

Open the protected UI directly:

```text
https://router.example.com/usage-logs/common
```

Expected outcomes:

- browser is redirected to Router SSO login
- after IdP completion, browser lands on `/usage-logs/common`
- the `new-api` UI renders instead of a login form

Confirm the SSO-backed `new-api` user:

```bash
curl -sk "${NEWAPI_BASE_URL}/api/user/self" \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}" | \
  jq '{id: .data.id, oidc_id: .data.oidc_id, group: .data.group, role: .data.role}'
```

Capture the authoritative private group from `new-api`:

```bash
export PRIVATE_GROUP="$(curl -sk "${NEWAPI_BASE_URL}/api/user/self" \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}" | \
  jq -r '.data.group')"
```

Expected outcomes:

- `oidc_id` is populated
- `group` starts with `private-`
- `role` matches the Router SSO assertion role

Triage:

- if UI loops back to login, confirm the browser accepted the `session` cookie from `new-api`
- if `/api/user/self` returns `401`, the copied cookie is stale or from the wrong origin
- if `/api/user/self` returns `500`, inspect `docker compose --env-file .env.local logs new-api --tail=200` for Router SSO user upsert failures

## 4. routerctl Login and Bind

Login through Router SSO from the CLI:

```bash
uv sync --group dev
uv run routerctl auth login --router-base-url "${ROUTER_BASE_URL}"
uv run routerctl auth status --session-file "${ROUTERCTL_SESSION_FILE}" | jq .
```

Expected outcomes:

- browser-assisted login completes
- `auth status` prints `router_base_url`, `access_token`, `expires_at`, and `principal`

Capture the router session fields used later:

```bash
export ROUTER_SESSION_TOKEN="$(jq -r '.access_token' "${ROUTERCTL_SESSION_FILE}")"
```

Bind Claude Code and Codex:

```bash
uv run routerctl claude bind --session-file "${ROUTERCTL_SESSION_FILE}"
uv run routerctl codex bind --session-file "${ROUTERCTL_SESSION_FILE}"
```

Expected outcomes:

- Claude bind prints `Claude Max credential bound`
- Codex bind prints `Codex credential bound`
- both results show `Visibility  private`

Triage:

- if CLI says `NOT_AUTHENTICATED`, rerun `routerctl auth login`
- if Claude calls later fail with expired upstream auth, rerun `uv run routerctl claude bind ...`
- if Codex bind fails with `BINARY_NOT_FOUND`, install the `codex` binary first or pass `--codex-bin <path>`

## 5. Verify Router Credential State

List the Router-side upstream credentials:

```bash
curl -sk "${ROUTER_BASE_URL}/me/upstream-credentials" \
  -H "Authorization: Bearer ${ROUTER_SESSION_TOKEN}" | \
  jq '.data[] | {id, provider, auth_kind, visibility, owner_principal_id, source}'
```

Expected outcomes:

- at least one `openai-codex` credential exists
- at least one `claude-max` credential exists
- both begin as `visibility: "private"`

Capture IDs for the share/unshare steps:

```bash
export CODEX_CREDENTIAL_ID="$(curl -sk "${ROUTER_BASE_URL}/me/upstream-credentials" \
  -H "Authorization: Bearer ${ROUTER_SESSION_TOKEN}" | \
  jq -r '.data[] | select(.provider=="openai-codex") | .id' | head -n1)"

export CLAUDE_CREDENTIAL_ID="$(curl -sk "${ROUTER_BASE_URL}/me/upstream-credentials" \
  -H "Authorization: Bearer ${ROUTER_SESSION_TOKEN}" | \
  jq -r '.data[] | select(.provider=="claude-max") | .id' | head -n1)"
```

## 6. Verify new-api Channel Sync

Codex bridge channel:

```bash
curl -sk "${NEWAPI_BASE_URL}/api/channel/search?keyword=router-codex&group=${PRIVATE_GROUP}&page_size=20" \
  -H "Authorization: ${NEWAPI_ADMIN_ACCESS_TOKEN}" \
  -H "New-Api-User: ${NEWAPI_ADMIN_USER_ID}" | \
  jq '.data.items[] | {id, name, type, group, models, base_url, tag, status}'
```

Claude bridge channel:

```bash
curl -sk "${NEWAPI_BASE_URL}/api/channel/search?keyword=router-claude-max&group=${PRIVATE_GROUP}&page_size=20" \
  -H "Authorization: ${NEWAPI_ADMIN_ACCESS_TOKEN}" \
  -H "New-Api-User: ${NEWAPI_ADMIN_USER_ID}" | \
  jq '.data.items[] | {id, name, type, group, models, base_url, tag, status}'
```

Expected outcomes:

- Codex bridge channel `type` is `1` (OpenAI-compatible)
- Claude bridge channel `type` is `14`
- both channels have `group` equal to `${PRIVATE_GROUP}`
- Codex bridge channel has `tag` equal to `router-oauth-bridge`
- Claude bridge channel has `tag` equal to `router-oauth`
- Codex bridge `base_url` points at `/bridge/upstreams/credentials/<id>/openai`
- Claude bridge `base_url` points at `/bridge/upstreams/credentials/<id>/anthropic`

Triage:

- if no channel is returned, check `ENTERPRISE_LLM_PROXY_NEWAPI_SYNC_ENABLED=true`
- if Router has the credential but `new-api` does not, inspect `docker compose --env-file .env.local logs app --tail=200` for admin sync failures
- if admin search returns `401` or `403`, verify `NEWAPI_ADMIN_ACCESS_TOKEN` and `NEWAPI_ADMIN_USER_ID`

## 7. Create a Private Smoke Token in new-api

Create the token:

```bash
curl -sk "${NEWAPI_BASE_URL}/api/token/" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}" \
  -d "{\"name\":\"router-sso-private-smoke\",\"expired_time\":-1,\"remain_quota\":500000,\"unlimited_quota\":true,\"group\":\"${PRIVATE_GROUP}\",\"model_limits_enabled\":false}"
```

Expected outcomes:

- response contains `"success": true`

Look up the token ID:

```bash
export PRIVATE_TOKEN_ID="$(curl -sk "${NEWAPI_BASE_URL}/api/token/?p=1&size=50" \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}" | \
  jq -r '.data.items[] | select(.name=="router-sso-private-smoke") | .id' | head -n1)"
```

Reveal the actual key:

```bash
export PRIVATE_TOKEN_KEY="$(curl -sk "${NEWAPI_BASE_URL}/api/token/${PRIVATE_TOKEN_ID}/key" \
  -X POST \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}" | \
  jq -r '.data.key')"
```

Expected outcomes:

- `PRIVATE_TOKEN_ID` is non-empty
- `PRIVATE_TOKEN_KEY` is non-empty and is the exact bearer token to use against `/v1/*`

Triage:

- if create succeeds but lookup returns nothing, increase page size or search for the token name in the UI
- if `/api/token/<id>/key` fails, confirm the same browser session cookie still works for `/api/user/self`

## 8. Private-Path Model Smoke

Automated real-upstream smoke:

```bash
export NEWAPI_BASE_URL="https://newapi.example.com"

# Uses NEWAPI_SESSION_COOKIE, ROUTER_SESSION_TOKEN, or
# ~/.enterprise-llm-proxy/session.json to create a temporary new-api token.
scripts/verify-newapi-real-upstreams.py --env-file .env.local --insecure
```

If a New API smoke token already exists, the script can skip browser/CLI SSO
and call the live upstream path directly:

```bash
export NEWAPI_BASE_URL="https://newapi.example.com"
export NEWAPI_PRIVATE_TOKEN_KEY="<new-api-token-key>"

scripts/verify-newapi-real-upstreams.py \
  --skip-router-credential-check
```

Add `--skip-codex` or `--skip-claude` only when isolating one upstream.

Codex path:

```bash
export CODEX_REQUEST_ID="runbook-codex-$(date +%s)"

curl -sk "${NEWAPI_BASE_URL}/v1/responses" \
  -H "Authorization: Bearer ${PRIVATE_TOKEN_KEY}" \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: ${CODEX_REQUEST_ID}" \
  -d '{"model":"gpt-5.4","input":[{"role":"user","content":"Reply with OK"}],"stream":false}' | \
  jq '{id, model, output_text, usage}'
```

Claude path:

```bash
export CLAUDE_REQUEST_ID="runbook-claude-$(date +%s)"

curl -sk "${NEWAPI_BASE_URL}/v1/messages" \
  -H "Authorization: Bearer ${PRIVATE_TOKEN_KEY}" \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: ${CLAUDE_REQUEST_ID}" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":64,"messages":[{"role":"user","content":"Reply with OK"}]}' | \
  jq '{id, model, content, usage}'
```

Expected outcomes:

- both calls return `200`
- Codex response contains `.output_text` or populated `.output`
- Claude response contains `.content[0].text`
- both responses include usage data

Triage:

- if either call fails with a channel-selection error, confirm the bound channel exists in `${PRIVATE_GROUP}`
- if Claude fails with expired upstream auth, rerun `uv run routerctl claude bind --session-file "${ROUTERCTL_SESSION_FILE}"`
- if Codex fails after bind, rerun `uv run routerctl codex bind --session-file "${ROUTERCTL_SESSION_FILE}"`

## 9. Share, Enterprise Smoke, Then Unshare

Share the Codex credential into the enterprise pool:

```bash
curl -sk "${ROUTER_BASE_URL}/me/upstream-credentials/${CODEX_CREDENTIAL_ID}/share" \
  -X POST \
  -H "Authorization: Bearer ${ROUTER_SESSION_TOKEN}" | \
  jq '{id, provider, visibility}'
```

Expected outcomes:

- response returns `visibility: "enterprise_pool"`

Confirm the synced channel now includes the enterprise group:

```bash
curl -sk "${NEWAPI_BASE_URL}/api/channel/search?keyword=router-codex&group=${PRIVATE_GROUP}&page_size=20" \
  -H "Authorization: ${NEWAPI_ADMIN_ACCESS_TOKEN}" \
  -H "New-Api-User: ${NEWAPI_ADMIN_USER_ID}" | \
  jq '.data.items[] | {id, name, group}'
```

Expected outcomes:

- channel `group` becomes `${PRIVATE_GROUP},${ENTERPRISE_GROUP}`

Create an enterprise-group token:

```bash
curl -sk "${NEWAPI_BASE_URL}/api/token/" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}" \
  -d "{\"name\":\"router-sso-enterprise-smoke\",\"expired_time\":-1,\"remain_quota\":500000,\"unlimited_quota\":true,\"group\":\"${ENTERPRISE_GROUP}\",\"model_limits_enabled\":false}"

export ENTERPRISE_TOKEN_ID="$(curl -sk "${NEWAPI_BASE_URL}/api/token/?p=1&size=50" \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}" | \
  jq -r '.data.items[] | select(.name=="router-sso-enterprise-smoke") | .id' | head -n1)"

export ENTERPRISE_TOKEN_KEY="$(curl -sk "${NEWAPI_BASE_URL}/api/token/${ENTERPRISE_TOKEN_ID}/key" \
  -X POST \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}" | \
  jq -r '.data.key')"
```

Run the enterprise-path model smoke:

```bash
export ENTERPRISE_REQUEST_ID="runbook-enterprise-$(date +%s)"

curl -sk "${NEWAPI_BASE_URL}/v1/responses" \
  -H "Authorization: Bearer ${ENTERPRISE_TOKEN_KEY}" \
  -H "Content-Type: application/json" \
  -H "X-Request-Id: ${ENTERPRISE_REQUEST_ID}" \
  -d '{"model":"gpt-5.4","input":[{"role":"user","content":"Reply with OK"}],"stream":false}' | \
  jq '{id, model, output_text, usage}'
```

Expected outcomes:

- the enterprise token works only while the credential is shared

Unshare and confirm rollback:

```bash
curl -sk "${ROUTER_BASE_URL}/me/upstream-credentials/${CODEX_CREDENTIAL_ID}/unshare" \
  -X POST \
  -H "Authorization: Bearer ${ROUTER_SESSION_TOKEN}" | \
  jq '{id, provider, visibility}'

curl -sk "${NEWAPI_BASE_URL}/api/channel/search?keyword=router-codex&group=${PRIVATE_GROUP}&page_size=20" \
  -H "Authorization: ${NEWAPI_ADMIN_ACCESS_TOKEN}" \
  -H "New-Api-User: ${NEWAPI_ADMIN_USER_ID}" | \
  jq '.data.items[] | {id, name, group}'
```

Expected outcomes:

- Router credential returns to `visibility: "private"`
- new-api channel `group` returns to `${PRIVATE_GROUP}`

Enterprise-path negative check after unshare:

```bash
curl -sk "${NEWAPI_BASE_URL}/v1/responses" \
  -H "Authorization: Bearer ${ENTERPRISE_TOKEN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.4","input":[{"role":"user","content":"Reply with OK"}],"stream":false}'
```

Expected outcomes:

- request is no longer successful
- typical failure shape is a channel-selection error because `${ENTERPRISE_GROUP}` no longer has the shared Codex channel

## 10. Audit and Usage Visibility

User-visible logs for the private Codex request:

```bash
curl -sk "${NEWAPI_BASE_URL}/api/log/self?p=1&size=20&request_id=${CODEX_REQUEST_ID}" \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}" | \
  jq '.data.items[0] | {model_name, token_name, channel, group, request_id}'
```

User-visible stats:

```bash
curl -sk "${NEWAPI_BASE_URL}/api/log/self/stat" \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}" | \
  jq '.data'
```

Admin-visible logs for the same request:

```bash
curl -sk "${NEWAPI_BASE_URL}/api/log/?p=1&size=20&request_id=${CODEX_REQUEST_ID}" \
  -H "Authorization: ${NEWAPI_ADMIN_ACCESS_TOKEN}" \
  -H "New-Api-User: ${NEWAPI_ADMIN_USER_ID}" | \
  jq '.data.items[0] | {username, model_name, token_name, channel, group, request_id}'
```

Admin-visible aggregate stats:

```bash
curl -sk "${NEWAPI_BASE_URL}/api/log/stat?group=${PRIVATE_GROUP}" \
  -H "Authorization: ${NEWAPI_ADMIN_ACCESS_TOKEN}" \
  -H "New-Api-User: ${NEWAPI_ADMIN_USER_ID}" | \
  jq '.data'
```

Expected outcomes:

- the user log query returns the request that was just made
- the admin log query returns the same `request_id` with channel and group filled in
- the stats endpoints return non-zero quota or traffic after successful calls

Triage:

- if logs are missing, retry after a short delay and re-filter by `request_id`
- if admin logs show the request but user logs do not, confirm you queried with the same browser session that created the token
- if channel is empty in logs, inspect `docker compose --env-file .env.local logs new-api --tail=200`

## 11. Cleanup

Remove the smoke tokens:

```bash
curl -sk "${NEWAPI_BASE_URL}/api/token/${PRIVATE_TOKEN_ID}" \
  -X DELETE \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}"

curl -sk "${NEWAPI_BASE_URL}/api/token/${ENTERPRISE_TOKEN_ID}" \
  -X DELETE \
  -H "Cookie: session=${NEWAPI_SESSION_COOKIE}"
```

Log out the CLI session:

```bash
uv run routerctl auth logout --session-file "${ROUTERCTL_SESSION_FILE}"
```

Expected outcomes:

- smoke tokens are deleted
- local `routerctl` session is cleared

## 12. Fast Failure Map

- Browser redirects forever to `/sso/login`
  - check `nginx` can reach `app:/sso/assertion`
  - verify router session cookie and `new-api` `session` cookie are both being set
- `routerctl ... bind` succeeds but channel is absent
  - check `ENTERPRISE_LLM_PROXY_NEWAPI_SYNC_ENABLED`
  - verify `ENTERPRISE_LLM_PROXY_NEWAPI_BASE_URL`, `ENTERPRISE_LLM_PROXY_NEWAPI_ADMIN_ACCESS_TOKEN`, `ENTERPRISE_LLM_PROXY_NEWAPI_ADMIN_USER_ID`
- Private token call fails
  - verify bound channels exist in `${PRIVATE_GROUP}`
  - verify requested model is listed on that channel
- Enterprise token still works after unshare
  - confirm the shared channel’s `group` really dropped `${ENTERPRISE_GROUP}`
  - confirm the enterprise token itself is pinned to `${ENTERPRISE_GROUP}` and not `auto`
