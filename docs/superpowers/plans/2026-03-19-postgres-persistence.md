# PostgreSQL Persistence Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pilot's in-memory credentials, quotas, usage ledger, and developer API keys with PostgreSQL-backed persistence while preserving the current HTTP API behavior.

**Architecture:** Introduce SQLAlchemy/Alembic-backed repositories behind the existing services, with a small database wiring layer in app startup and a secret codec boundary for provider tokens. Keep routing/quota/API-key behavior in services, and move durable state, lease coordination, and aggregation into repository implementations.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL, pytest

---

## File Structure

### New files

- `src/enterprise_llm_proxy/db.py`
- `src/enterprise_llm_proxy/security.py`
- `src/enterprise_llm_proxy/repositories/base.py`
- `src/enterprise_llm_proxy/repositories/models.py`
- `src/enterprise_llm_proxy/repositories/credentials.py`
- `src/enterprise_llm_proxy/repositories/quotas.py`
- `src/enterprise_llm_proxy/repositories/usage.py`
- `src/enterprise_llm_proxy/repositories/api_keys.py`
- `alembic.ini`
- `alembic/env.py`
- `alembic/script.py.mako`
- `alembic/versions/20260319_01_postgres_persistence.py`
- `tests/conftest.py`
- `tests/repositories/test_postgres_credentials.py`
- `tests/repositories/test_postgres_quotas.py`
- `tests/repositories/test_postgres_usage.py`
- `tests/repositories/test_postgres_api_keys.py`
- `infra/local/docker-compose.postgres.yml`

### Modified files

- `pyproject.toml`
- `.env.example`
- `README.md`
- `infra/kubernetes/configmap.yaml`
- `infra/kubernetes/secrets.example.yaml`
- `src/enterprise_llm_proxy/config.py`
- `src/enterprise_llm_proxy/app.py`
- `src/enterprise_llm_proxy/services/credentials.py`
- `src/enterprise_llm_proxy/services/quotas.py`
- `src/enterprise_llm_proxy/services/usage.py`
- `src/enterprise_llm_proxy/services/api_keys.py`
- `tests/test_credentials.py`
- `tests/test_developer_access.py`
- `tests/test_inference_api.py`
- `tests/test_admin_api.py`
- `tests/test_upstream_oauth.py`

## Chunk 1: Database Foundations

### Task 1: Add failing configuration tests for database-backed startup

**Files:**
- Modify: `tests/test_config.py`
- Modify: `src/enterprise_llm_proxy/config.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_settings_read_database_url() -> None:
    ...


def test_settings_default_sqlalchemy_echo_is_false() -> None:
    ...
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `uv run pytest -q tests/test_config.py`
Expected: FAIL because database settings do not exist yet.

- [ ] **Step 3: Add minimal settings**

```python
database_url: str | None = None
sqlalchemy_echo: bool = False
```

- [ ] **Step 4: Re-run the targeted tests**

Run: `uv run pytest -q tests/test_config.py`
Expected: PASS

### Task 2: Add SQLAlchemy/Alembic scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `src/enterprise_llm_proxy/db.py`
- Create: `src/enterprise_llm_proxy/repositories/base.py`
- Create: `src/enterprise_llm_proxy/repositories/models.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/20260319_01_postgres_persistence.py`

- [ ] **Step 1: Write a failing smoke test for metadata creation**

```python
def test_sqlalchemy_metadata_includes_persistence_tables() -> None:
    ...
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run: `uv run pytest -q tests/test_config.py::test_sqlalchemy_metadata_includes_persistence_tables`
Expected: FAIL because the metadata/models do not exist yet.

- [ ] **Step 3: Add dependencies and scaffolding**

```toml
dependencies = [
  "alembic>=1.14.0,<2.0.0",
  "psycopg[binary]>=3.2.0,<4.0.0",
]
```

```python
Base = DeclarativeBase
def create_engine_from_settings(...): ...
def create_session_factory(...): ...
```

- [ ] **Step 4: Implement the first Alembic migration**

Create the five approved tables:
- `provider_credentials`
- `quotas`
- `usage_events`
- `usage_event_teams`
- `platform_api_keys`

- [ ] **Step 5: Re-run the targeted smoke test**

Run: `uv run pytest -q tests/test_config.py::test_sqlalchemy_metadata_includes_persistence_tables`
Expected: PASS

### Task 3: Add a secret codec boundary

**Files:**
- Create: `src/enterprise_llm_proxy/security.py`
- Modify: `tests/test_credentials.py`

- [ ] **Step 1: Write the failing unit test**

```python
def test_passthrough_secret_codec_returns_original_value() -> None:
    ...
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run: `uv run pytest -q tests/test_credentials.py::test_passthrough_secret_codec_returns_original_value`
Expected: FAIL because no codec abstraction exists yet.

- [ ] **Step 3: Add the codec abstraction**

```python
class SecretCodec(Protocol): ...

class PassthroughSecretCodec:
    def encode(self, plain: str | None) -> str | None: ...
    def decode(self, stored: str | None) -> str | None: ...
```

- [ ] **Step 4: Re-run the targeted test**

Run: `uv run pytest -q tests/test_credentials.py::test_passthrough_secret_codec_returns_original_value`
Expected: PASS

## Chunk 2: Repository Implementations

### Task 4: Implement PostgreSQL credential repository with lease-aware selection

**Files:**
- Create: `src/enterprise_llm_proxy/repositories/credentials.py`
- Modify: `src/enterprise_llm_proxy/services/credentials.py`
- Create: `tests/repositories/test_postgres_credentials.py`
- Modify: `tests/test_credentials.py`

- [ ] **Step 1: Write failing repository tests**

```python
def test_repository_round_trips_provider_credential(postgres_session_factory): ...
def test_repository_selects_weighted_lru_candidate(postgres_session_factory): ...
def test_repository_skips_cooldown_and_saturated_candidates(postgres_session_factory): ...
def test_repository_release_clamps_concurrent_leases_at_zero(postgres_session_factory): ...
```

- [ ] **Step 2: Run the repository tests to verify they fail**

Run: `uv run pytest -q tests/repositories/test_postgres_credentials.py`
Expected: FAIL because the repository does not exist yet.

- [ ] **Step 3: Implement the repository and service integration**

```python
class PostgresCredentialRepository:
    def create_credential(...): ...
    def select(...): ...
    def release(...): ...
    def mark_cooldown(...): ...
```

Use `SELECT ... FOR UPDATE SKIP LOCKED` for lease acquisition.

- [ ] **Step 4: Re-run the repository tests**

Run: `uv run pytest -q tests/repositories/test_postgres_credentials.py`
Expected: PASS

- [ ] **Step 5: Re-run the existing credential service tests**

Run: `uv run pytest -q tests/test_credentials.py`
Expected: PASS

### Task 5: Implement PostgreSQL quota and usage repositories

**Files:**
- Create: `src/enterprise_llm_proxy/repositories/quotas.py`
- Create: `src/enterprise_llm_proxy/repositories/usage.py`
- Modify: `src/enterprise_llm_proxy/services/quotas.py`
- Modify: `src/enterprise_llm_proxy/services/usage.py`
- Create: `tests/repositories/test_postgres_quotas.py`
- Create: `tests/repositories/test_postgres_usage.py`

- [ ] **Step 1: Write failing quota and usage repository tests**

```python
def test_quota_repository_sets_and_lists_rules(postgres_session_factory): ...
def test_usage_repository_records_event_and_team_memberships(postgres_session_factory): ...
def test_usage_repository_totals_successful_tokens_for_user(postgres_session_factory): ...
def test_usage_repository_totals_successful_tokens_for_team(postgres_session_factory): ...
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `uv run pytest -q tests/repositories/test_postgres_quotas.py tests/repositories/test_postgres_usage.py`
Expected: FAIL because the repositories do not exist yet.

- [ ] **Step 3: Implement the repositories and adapt the services**

```python
class PostgresQuotaRepository: ...
class PostgresUsageRepository: ...
class QuotaService:
    def __init__(self, usage_repository, quota_repository): ...
```

- [ ] **Step 4: Re-run the targeted repository tests**

Run: `uv run pytest -q tests/repositories/test_postgres_quotas.py tests/repositories/test_postgres_usage.py`
Expected: PASS

### Task 6: Implement PostgreSQL platform API key repository

**Files:**
- Create: `src/enterprise_llm_proxy/repositories/api_keys.py`
- Modify: `src/enterprise_llm_proxy/services/api_keys.py`
- Create: `tests/repositories/test_postgres_api_keys.py`
- Modify: `tests/test_developer_access.py`

- [ ] **Step 1: Write the failing repository tests**

```python
def test_api_key_repository_round_trips_principal_snapshot(postgres_session_factory): ...
def test_api_key_repository_finds_record_by_hash(postgres_session_factory): ...
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `uv run pytest -q tests/repositories/test_postgres_api_keys.py`
Expected: FAIL because the repository does not exist yet.

- [ ] **Step 3: Implement repository-backed API key storage**

```python
class PostgresPlatformApiKeyRepository: ...
class PlatformApiKeyService:
    def __init__(self, repository): ...
```

- [ ] **Step 4: Re-run the targeted tests**

Run: `uv run pytest -q tests/repositories/test_postgres_api_keys.py`
Expected: PASS

## Chunk 3: Application Wiring and Behavior Preservation

### Task 7: Rewire app startup to build repository-backed services

**Files:**
- Modify: `src/enterprise_llm_proxy/app.py`
- Modify: `src/enterprise_llm_proxy/config.py`
- Modify: `tests/test_app_bootstrap.py`
- Modify: `tests/test_inference_api.py`
- Modify: `tests/test_admin_api.py`
- Modify: `tests/test_developer_access.py`
- Modify: `tests/test_upstream_oauth.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write failing app-level persistence tests**

```python
def test_app_reuses_persisted_platform_api_key_across_app_recreation(...): ...
def test_app_reuses_persisted_quota_and_usage_across_app_recreation(...): ...
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `uv run pytest -q tests/test_developer_access.py tests/test_inference_api.py`
Expected: FAIL because app startup still constructs in-memory state.

- [ ] **Step 3: Add database wiring**

```python
engine = create_engine_from_settings(settings)
session_factory = create_session_factory(engine)
credential_repository = PostgresCredentialRepository(...)
...
```

- [ ] **Step 4: Re-run the targeted tests**

Run: `uv run pytest -q tests/test_developer_access.py tests/test_inference_api.py`
Expected: PASS

### Task 8: Add local PostgreSQL test support and migration workflow

**Files:**
- Create: `infra/local/docker-compose.postgres.yml`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `infra/kubernetes/configmap.yaml`
- Modify: `infra/kubernetes/secrets.example.yaml`

- [ ] **Step 1: Add local infrastructure and env documentation**

Document:
- `ENTERPRISE_LLM_PROXY_DATABASE_URL`
- Alembic upgrade command
- local Postgres startup flow

- [ ] **Step 2: Add migration and local verification docs**

```bash
docker compose -f infra/local/docker-compose.postgres.yml up -d
uv run alembic upgrade head
uv run pytest -q
```

- [ ] **Step 3: Rebuild the README/local docs**

Run: `sed -n '1,260p' README.md`
Expected: updated setup reflects PostgreSQL persistence and Alembic workflow.

## Chunk 4: Verification and Finish

### Task 9: Run full verification

**Files:**
- Verify only

- [ ] **Step 1: Run Python tests**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 2: Run frontend tests**

Run: `cd web && npm test`
Expected: PASS

- [ ] **Step 3: Run frontend build**

Run: `cd web && npm run build`
Expected: PASS

- [ ] **Step 4: Run CLI and migration verification**

Run: `uv run alembic upgrade head`
Expected: PASS

- [ ] **Step 5: Review git diff**

Run: `git diff --stat`
Expected: coherent persistence-focused change set
