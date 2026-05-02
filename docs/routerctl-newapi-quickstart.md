# routerctl + New API Quickstart

New API is the public gateway for `/`, `/api/*`, and `/v1/*`. Router remains
the credential bridge behind the developer portal at `/portal/setup`.

## 1. Install and log in

Use the Router control-plane base URL, not the `/v1` API base:

```bash
routerctl auth login --router-base-url https://ai.neurasea.com
routerctl auth status
```

## 2. Bind local OAuth credentials

Bind the local subscriptions you want Router to bridge:

```bash
routerctl codex bind
routerctl claude bind
```

`routerctl codex bind` imports the local Codex/ChatGPT OAuth session. It does
not mint an official OpenAI API key. Router stores the OAuth-backed credential
and exposes a bridge upstream for New API.

## 3. Confirm New API channel sync

After a credential is active, New API channel sync should create a channel that
points back to Router:

- Codex bridge base URL: `/bridge/upstreams/credentials/<id>/openai`
- Claude bridge base URL: `/bridge/upstreams/credentials/<id>/anthropic`

If the Router credential exists but the New API channel is missing, ask an
admin to inspect the sync task or run the admin sync endpoint.

## 4. Call through New API

Create a New API token in the New API console, then call the OpenAI-compatible
endpoint:

```bash
curl https://ai.neurasea.com/v1/responses \
  -H "Authorization: Bearer <new-api-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai-codex/gpt-5-codex",
    "input": "Say hello from the Router bridge."
  }'
```

Codex OAuth-backed models use the `openai-codex/` prefix. Claude Max
OAuth-backed models use the `claude-max/` prefix.
