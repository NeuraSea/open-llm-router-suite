# Open LLM Router Suite

Open LLM Router Suite packages an enterprise-ready token router solution around
[New API](https://github.com/QuantumNous/new-api), with Router SSO,
OAuth-to-API bridging, `routerctl` credential binding, LibreChat as the chat
entrypoint, and CC Switch for local coding-agent client launch/model switching.

Landing page: https://neurasea.github.io/open-llm-router-suite/

API relay: https://ai.neurasea.com

Verified developer portal: https://api.lingtai.ai/portal/setup

routerctl + New API quickstart:
https://github.com/NeuraSea/open-llm-router-suite/blob/main/docs/routerctl-newapi-quickstart.md

The repository is AGPLv3 because the solution depends on and extends New API,
which is AGPLv3.

## Architecture

- **New API** is the primary control plane and gateway for users, channels,
  tokens, usage, logs, billing, and model routing.
- **Router** is a FastAPI service that owns OIDC callback handling, Router SSO
  assertions for New API, upstream OAuth credential import, bridge endpoints,
  and New API channel sync.
- **routerctl** is the local CLI for `auth login/status/logout`,
  `claude bind`, `codex bind`, and model discovery/configuration.
- **LibreChat** is exposed as the New API console chat entrypoint at `/chat/`
  and uses a custom OpenAI-compatible endpoint pointed at New API `/v1`.
- **CC Switch** remains an external local tool for launching Claude Code/Codex
  and switching models; this repo does not vendor CC Switch.
- **Casdoor** is the recommended OIDC identity provider. It can front Feishu
  OAuth, company SSO, and WeChat QR login while exposing one OIDC contract to
  Router, New API, and LibreChat.

## Public Routes

Production entrypoints:

- New API stays on `/` and owns the user-facing console, token creation,
  channels, logs, and `/v1` API calls.
- Router developer setup lives at `/portal/setup`, where users install
  `routerctl` and bind Codex/Claude OAuth credentials.
- Router API docs live at `/portal/docs` and explain the model prefixes and
  OpenAI-compatible endpoints.

Router owns:

- `/sso/login`
- `/auth/oidc/callback`
- `/sso/assertion`
- `/bridge/upstreams/...`
- `/me/upstream-credentials/*`
- `/cli/*`
- `/install/routerctl.*`

New API owns:

- `/`
- `/api/*`
- `/v1/*`
- usage, token, channel, model, and admin surfaces

LibreChat owns:

- `/chat/`

nginx uses `auth_request /_sso_assertion` to ask Router for a short-lived
`X-Router-SSO-Assertion` JWT and forwards that assertion into New API.

## Local Setup

Create configuration:

```bash
cp .env.example .env.local
```

Generate Router SSO RSA keys and fill these values:

```bash
ENTERPRISE_LLM_PROXY_ROUTER_SSO_PRIVATE_KEY_PEM=...
ROUTER_SSO_PUBLIC_KEY_PEM=...
NEWAPI_SESSION_SECRET=...
ENTERPRISE_LLM_PROXY_NEWAPI_ADMIN_ACCESS_TOKEN=...
ENTERPRISE_LLM_PROXY_BRIDGE_UPSTREAM_API_KEY=...
```

Start Router + New API:

```bash
docker compose --env-file .env.local up --build
```

Start with LibreChat:

```bash
docker compose --env-file .env.local --profile librechat up --build
```

The example hosts are:

- Router/New API: `https://router.example.com`
- Optional split host: `https://newapi.example.com`
- Chat: `https://router.example.com/chat/`
- OIDC issuer: `https://sso.example.com`

For local-only testing, either use plain container ports or place your own TLS
reverse proxy in front of nginx and map `router.example.com` to your machine.

## Authentication

Recommended production shape:

1. Casdoor connects to Feishu OAuth, company SSO, WeChat QR login, or any other
   upstream identity provider.
2. Router uses Casdoor OIDC via `ENTERPRISE_LLM_PROXY_OIDC_*`.
3. New API trusts Router SSO assertions.
4. LibreChat uses the same Casdoor issuer with its own OIDC client.

Direct Feishu OIDC remains available as a preset through
`ENTERPRISE_LLM_PROXY_FEISHU_*` when you do not want Casdoor in front of
Feishu.

## Developer Workflow

For the verified Lingtai deployment, start at:

- New API console and `/v1`: `https://api.lingtai.ai`
- routerctl / OAuth binding guide: `https://api.lingtai.ai/portal/setup`
- product API docs: `https://api.lingtai.ai/portal/docs`

Install and log in:

```bash
uv run routerctl auth login --router-base-url https://router.example.com
uv run routerctl auth status
```

Bind local upstream OAuth credentials:

```bash
uv run routerctl claude bind
uv run routerctl codex bind
```

After binding, Router syncs the OAuth-backed bridge into New API as a channel.
Create a New API token in the New API console, then call `/v1` with the synced
model prefix, for example `openai-codex/gpt-5-codex` or
`claude-max/claude-sonnet-4-6`.

Discover and configure models:

```bash
uv run routerctl models list
uv run routerctl models config
```

Launch coding clients through CC Switch:

```bash
cc-switch claude
cc-switch codex
```

`routerctl` does not launch Claude Code or Codex directly. It only manages
Router authentication, upstream credential binding, and model discovery.

## Development Checks

Backend:

```bash
uv sync --group dev
uv run pytest -q
```

Frontend:

```bash
cd web
npm install
npm test
npm run build
```

New API vendored fork lane:

```bash
cd third_party/new-api
go test ./middleware ./service ./controller
```

## Credits

This solution stands on existing open-source projects. See
[CREDITS.md](./CREDITS.md) and [NOTICE.md](./NOTICE.md).
