# New API Vendored Fork Handoff

`third_party/new-api` is the New API fork lane for Router SSO integration.

## Scope Split

- Parent repo owns Router SSO issuance, OIDC callback handling, `oauth-bridge`,
  `routerctl`, nginx, Docker Compose, LibreChat wiring, and docs.
- New API owns gateway runtime behavior for channels, tokens, models, usage,
  billing, audit, and the New API-side Router SSO middleware/UI.
- The contract is: Router issues short-lived SSO assertions and syncs
  admin-managed channels; New API consumes those assertions and serves the
  gateway/admin surface from the vendored fork lane.

## Fork Model

- Maintain a long-lived fork branch named `singularity-router-sso` or rename it
  before publishing if you want a neutral branch name.
- Do not remove New API's original name, author identity, or license notices.
- Keep Router-specific patches narrow so upstream New API merges remain cheap.
- To compare or refresh from upstream, use a separate clone of New API:

```bash
git clone https://github.com/QuantumNous/new-api.git /tmp/new-api-upstream
```

## Landing Order

1. Keep New API upstream notices and license files intact.
2. Commit Router-specific New API changes under `third_party/new-api`.
3. Commit parent Router/nginx/compose/docs changes that depend on those files.
4. Deploy only from a parent commit where Router and vendored New API tests pass.

## Required Checks

```bash
(cd third_party/new-api && go test ./middleware ./service ./controller)
uv run pytest -q tests/test_newapi_sync.py tests/test_router_sso.py
```

If Go is unavailable in the local environment, record that as a verification
gap before publishing.
