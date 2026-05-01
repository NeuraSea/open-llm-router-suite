# AGENTS.md

## Commands

```bash
# Run all tests (most tests use in-memory repos, no DB needed)
uv run pytest tests/ -q

# Run a single test file
uv run pytest tests/test_browser_portal.py -v

# Run the server locally
uv run uvicorn enterprise_llm_proxy.app:create_app --factory --host 0.0.0.0 --port 8000

# Apply DB migrations
uv run alembic upgrade head

# Check for unapplied migrations
uv run alembic check

# Build routerctl wheel for local distribution testing
uv build --wheel --out-dir dist/

# Build frontend (required when changing web/)
cd web && npm ci && npm run build
```

## Architecture

- **What it does**: Enterprise LLM gateway that pools Codex Max and OpenAI Codex OAuth subscriptions across developers. Exposes an OpenAI-compatible `/v1` API, proxying requests to credential pools. Handles billing quotas and usage tracking.
- **Auth flow**: Browser users authenticate via Feishu OIDC (`/auth/oidc/callback`) → JWT signed with `jwt_signing_secret` stored as a session cookie. All JWTs carry a `jti` claim; `POST /auth/server-logout` revokes it server-side via the `revoked_tokens` table.
- **CLI tool (routerctl)**: Developers install via `curl | bash` using a short-lived bootstrap token. The CLI completes a PKCE auth flow (`/auth/cli/authorize` → `/auth/cli/token`) to obtain a `cli_session` JWT. CLI auth state (pending PKCE challenges, Codex OAuth states) is stored as `CliAuthStateRecord` rows with a JSONB payload discriminated by `kind`.
- **PostgreSQL state**: All durable state (credentials, quotas, usage, CLI auth, revoked tokens) lives in Postgres. Without `DATABASE_URL`, the app starts with in-memory fallbacks — fine for tests, not for production.
- **Key layers**: FastAPI app (`app.py`) → service layer (`services/`) → repository layer (`repositories/`, SQLAlchemy 2.0) → domain models (`domain/`). `create_app()` wires everything together via constructor injection.

## Key Conventions

- **Tests don't need a real DB**: `create_app()` accepts `cli_auth_repository` and `revoked_token_repo` overrides. Tests inject `_InMemoryCliAuthRepository` / `_InMemoryRevokedTokenRepository`. Postgres integration tests are skipped automatically if `127.0.0.1:55432` is unavailable.
- **Postgres integration tests**: Use `ENTERPRISE_LLM_PROXY_TEST_DATABASE_URL` to override the default `postgresql+psycopg://router:router@127.0.0.1:55432/router_test`.
- **All settings use prefix `ENTERPRISE_LLM_PROXY_`**: Loaded from `.env` or `.env.local`. Copy `.env.example` → `.env.local` for local dev.
- **Token kinds**: `human_session` (8h, browser cookie), `cli_session` (8h, CLI), `client_access` (30d, API). Each has different TTL via settings.
- **Alembic revision chain**: `20260319_01` → `20260327_02` → `20260327_03` → `20260327_04` → `bca2a7b69d22` → `20260328_05` → `20260329_01` → `20260329_02`. New migrations must set `down_revision` to `20260329_02`.
- **CLI auth state kinds**: `pkce_challenge` and `codex_oauth_state` — both stored as `CliAuthStateRecord` with a JSONB `payload` column, replacing the old in-memory `pending_codex_oauth_states` dict.

## Gotchas

- **Python 3.12+ required**: `from datetime import UTC` is used throughout. `pyproject.toml` is set to `>=3.12` — 3.9/3.10/3.11 will fail at import time.
- **`routerctl_wheel_dir` defaults to `/app/dist`**: This path only exists inside the Docker image (built via `uv build --wheel --out-dir /app/dist`). Locally, set `ENTERPRISE_LLM_PROXY_ROUTERCTL_WHEEL_DIR=./dist` after running `uv build --wheel --out-dir dist/`.
- **`sweep_expired()` is a background task**: Wired in `create_app()` via FastAPI lifespan. Starts an asyncio loop that sleeps 3600s then calls `resolved_cli_auth_repo.sweep_expired()`. Only active when `database_url` is configured (in-memory repos have no-op sweep). Sweeps `cli_auth_state` and `consumed_jtis` rows past their `expires_at`.
- **Frontend assets are committed**: The built SPA lives in `src/enterprise_llm_proxy/static/ui/`. After changing `web/`, rebuild and commit the updated assets.
- **Feishu OIDC requires all four settings**: `feishu_client_id`, `feishu_client_secret`, `feishu_token_url`, and `feishu_userinfo_url` must all be set for OIDC to be enabled. Missing any one disables login silently.
- **`session_cookie_secure` defaults to `False`**: Must be set to `True` in production (HTTPS). The `.env.example` sets it correctly.

## Design System
Always read `DESIGN.md` before making any visual or UI decisions.
All font choices, colors, spacing, border-radius, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match `DESIGN.md`.

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
