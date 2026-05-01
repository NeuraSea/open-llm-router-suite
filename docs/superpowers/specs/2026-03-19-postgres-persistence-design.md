# PostgreSQL Persistence Design

**Date:** 2026-03-19
**Worktree:** `codex/pilot-hardening`
**Status:** Approved for implementation

## Goal

Replace the pilot's in-memory runtime state with PostgreSQL-backed persistence for the core control-plane state:

- provider credentials
- quotas
- usage events
- developer platform API keys

The implementation should keep the existing HTTP API behavior and service-level business rules stable while introducing explicit storage boundaries, Alembic-managed schema, and a future-proof path for secret encryption and operational hardening.

## Non-goals

This iteration intentionally does not include:

- JWT/session persistence
- `pending_codex_oauth_states` persistence
- KMS integration
- Redis caching or distributed locking
- background workers or async job infrastructure
- a persistent user directory or user table

## Approved Decisions

- Persist `credentials + quotas + usage + developer API keys` in PostgreSQL.
- Default the application to PostgreSQL-backed storage for this worktree's implementation.
- Keep a clean repository/storage boundary instead of wiring SQLAlchemy directly into business services.
- Manage schema with Alembic rather than application-startup auto-DDL.
- Persist sensitive tokens in PostgreSQL for now, but only through a dedicated secret codec boundary so KMS can be added later without changing service logic.
- Preserve current API semantics and domain model behavior unless persistence requires a narrowly scoped behavioral fix.

## Current State

The current application constructs in-memory services directly inside [`app.py`](/Users/aaron/Documents/workspace/enterprise-llm-proxy/.worktrees/codex/pilot-hardening/src/enterprise_llm_proxy/app.py):

- `CredentialPoolService`
- `QuotaService`
- `UsageLedger`
- `PlatformApiKeyService`

Those services currently own runtime dictionaries/lists instead of durable storage. This keeps the pilot simple, but it creates four major gaps:

1. State is lost on process restart.
2. Multi-instance routing cannot coordinate credential leases correctly.
3. Usage/quota enforcement only reflects one process's memory.
4. Sensitive provider credentials have no durable operational path.

## Architecture

The implementation should introduce four layers.

### 1. Config and Wiring

Application startup becomes responsible for:

- building the SQLAlchemy engine and session factory
- selecting the secret codec implementation
- instantiating repository implementations
- injecting those repositories into service objects

This keeps framework-level wiring in one place and prevents repository concerns from leaking through the request handlers.

### 2. Repository Layer

Add repository interfaces plus PostgreSQL-backed implementations for:

- provider credentials
- quotas
- usage events
- platform API keys

Repositories own:

- SQLAlchemy models
- query composition
- transaction/session usage
- row-to-domain mapping

Repositories do not own routing policy, quota policy, or bootstrap logic.

### 3. Service Layer

Existing services remain the primary location for business behavior:

- route selection
- accessibility rules
- weighted LRU behavior
- cooldown handling
- quota enforcement
- API key issuance/authentication
- usage recording

Services should operate on domain objects and repository interfaces, not ORM rows.

### 4. Secret Codec Boundary

Introduce a small abstraction for credential secret handling:

- `encode(plain: str | None) -> str | None`
- `decode(stored: str | None) -> str | None`

The initial implementation is a passthrough codec. Repository code uses this abstraction whenever reading or writing provider tokens so a later KMS-backed codec can replace it without touching service code or schema shape.

## Database Schema

The first Alembic migration should create five tables.

### `provider_credentials`

Stores the durable form of `ProviderCredential`.

Columns:

- `id TEXT PRIMARY KEY`
- `provider TEXT NOT NULL`
- `auth_kind TEXT NOT NULL`
- `account_id TEXT NOT NULL`
- `scopes TEXT[] NOT NULL`
- `state TEXT NOT NULL`
- `expires_at TIMESTAMPTZ NULL`
- `cooldown_until TIMESTAMPTZ NULL`
- `access_token_encrypted TEXT NULL`
- `refresh_token_encrypted TEXT NULL`
- `owner_principal_id TEXT NULL`
- `visibility TEXT NOT NULL`
- `source TEXT NULL`
- `last_selected_at TIMESTAMPTZ NULL`
- `concurrent_leases INTEGER NOT NULL DEFAULT 0`
- `max_concurrency INTEGER NOT NULL DEFAULT 1`
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

Indexes:

- `(provider, auth_kind, state)`
- `owner_principal_id`
- `visibility`
- `cooldown_until`

Notes:

- The `_encrypted` suffix is intentional even though the first codec is passthrough.
- `concurrent_leases` remains in the row because it is part of runtime routing coordination.

### `quotas`

Stores quota rules.

Columns:

- `scope_type TEXT NOT NULL`
- `scope_id TEXT NOT NULL`
- `limit INTEGER NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

Primary key:

- `(scope_type, scope_id)`

### `usage_events`

Stores the append-only usage ledger record.

Columns:

- `request_id TEXT PRIMARY KEY`
- `principal_id TEXT NOT NULL`
- `model_profile TEXT NOT NULL`
- `provider TEXT NOT NULL`
- `credential_id TEXT NOT NULL`
- `tokens_in INTEGER NOT NULL`
- `tokens_out INTEGER NOT NULL`
- `latency_ms INTEGER NOT NULL`
- `status TEXT NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL`

Indexes:

- `principal_id`
- `credential_id`
- `created_at`
- `(principal_id, status)`

### `usage_event_teams`

Stores the team memberships attached to a usage event so team quota aggregation does not depend on process memory.

Columns:

- `request_id TEXT NOT NULL`
- `team_id TEXT NOT NULL`

Primary key:

- `(request_id, team_id)`

Foreign key:

- `request_id -> usage_events.request_id`

Indexes:

- `team_id`

### `platform_api_keys`

Stores issued developer platform API keys.

Columns:

- `id TEXT PRIMARY KEY`
- `name TEXT NOT NULL`
- `key_prefix TEXT NOT NULL`
- `key_hash TEXT NOT NULL`
- `principal_id TEXT NOT NULL`
- `principal_email TEXT NOT NULL`
- `principal_name TEXT NOT NULL`
- `principal_role TEXT NOT NULL`
- `principal_team_ids TEXT[] NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL`

Indexes:

- unique `key_hash`
- `principal_id`

Notes:

- This table stores a principal snapshot instead of introducing a new user table.
- Authentication semantics remain consistent with the current in-memory implementation: restoring the principal from the key record itself.

## Runtime Design

### Repository Interfaces

The repository layer should expose interfaces that preserve the current service vocabulary instead of surfacing SQL-oriented primitives.

Suggested boundaries:

- `CredentialRepository`
  - list credentials
  - list credentials for owner
  - get credential by id
  - create credential
  - refresh/update credential fields
  - update visibility
  - acquire best credential candidate for `(provider, auth_kind, principal, excluded_ids)`
  - release lease
  - mark cooldown

- `QuotaRepository`
  - set quota
  - list quotas
  - get quota by `(scope_type, scope_id)`

- `UsageRepository`
  - record usage event with team memberships
  - list events
  - total successful usage for user
  - total successful usage for team

- `PlatformApiKeyRepository`
  - create key record
  - find by hash

### Transaction Boundaries

Use short-lived SQLAlchemy sessions and commit at clear state transitions.

Recommended boundaries:

- admin CRUD endpoints: one transaction per request
- developer API key creation: one transaction per key issuance
- usage recording: one transaction after executor success
- credential selection/lease acquisition: one transaction to atomically choose and increment a candidate
- credential release/cooldown update: one transaction per mutation

### Credential Selection and Lease Concurrency

This is the most important runtime change because in-memory weighted LRU logic currently assumes a single process.

PostgreSQL-backed selection should:

1. filter to accessible, active, non-cooled-down candidates with free capacity
2. order by:
   - `concurrent_leases ASC`
   - `last_selected_at ASC NULLS FIRST`
3. lock candidates with `FOR UPDATE SKIP LOCKED`
4. increment `concurrent_leases`
5. set `last_selected_at = now()`
6. commit before handing the credential back to the caller

This preserves the current weighted LRU semantics while preventing two router instances from oversubscribing the same credential row.

Release and cooldown updates should also be atomic:

- `release`: decrement `concurrent_leases`, clamped at zero
- `mark_cooldown`: decrement lease count, set `state = cooldown`, set `cooldown_until`

### Quota Aggregation

Keep quota evaluation synchronous for this iteration.

- user quota checks aggregate successful usage rows by `principal_id`
- team quota checks aggregate successful usage rows by joining `usage_event_teams`

This is simpler than introducing materialized counters in the first PostgreSQL version. If read volume later becomes a problem, precomputed counters can be added behind the repository layer without rewriting the HTTP/API surface.

### API Key Authentication

`PlatformApiKeyService.authenticate()` should keep hashing the presented key and resolving the stored record by `key_hash`.

The repository returns a `PlatformApiKey` domain object that reconstructs `Principal` from the stored snapshot fields. This keeps the current bearer-token flow intact without introducing external user dependencies.

## Configuration

Add application settings for:

- PostgreSQL database URL
- SQLAlchemy echo toggle
- secret codec selection hook or placeholder setting

The application should fail fast on startup if the database configuration is required but missing.

Alembic should read the same database URL source so local development and CI stay aligned.

## Testing Strategy

The implementation should keep the current unit-test coverage shape while adding persistence-specific coverage.

### Keep and Adapt Existing Service Tests

Current tests around:

- credential selection
- quota enforcement
- usage recording
- developer key issuance

should continue to pass, with services wired to repository-backed implementations instead of in-memory dictionaries where appropriate.

### Add Repository Integration Tests

New PostgreSQL integration tests should cover:

- credential create/read/update
- accessibility filtering
- weighted LRU selection
- `FOR UPDATE SKIP LOCKED` lease acquisition behavior
- quota reads/writes
- usage event recording and team aggregation
- API key lookup by hash

These tests should run against a real PostgreSQL database, ideally through an ephemeral local container or a dedicated CI service.

### End-to-End App Tests

App-level tests should verify:

- admin endpoints persist and reflect durable state
- usage survives app recreation
- quota enforcement still works after recorded usage
- developer API keys remain valid across app recreation

## Rollout Strategy

Implement in phases that preserve a passing baseline:

1. add database config, SQLAlchemy base/models, secret codec abstraction, and Alembic scaffolding
2. land repository interfaces and PostgreSQL implementations
3. refactor services to depend on repositories
4. rewire app startup to use repository-backed services
5. add integration tests and update local/deployment docs

Seed/bootstrap tooling may be added to make development easier, but it must be explicit and operator-invoked rather than implicit during startup.

## Risks and Mitigations

### Risk: lease accounting regresses under concurrency

Mitigation:

- move selection into an atomic repository method
- integration-test row locking behavior
- keep release/cooldown mutations idempotent and clamped

### Risk: quota queries become expensive

Mitigation:

- keep repository interfaces aggregate-based
- add indexes early
- defer counters/materialized views until actual pressure appears

### Risk: secret handling leaks through the codebase

Mitigation:

- confine token reads/writes to repository code plus secret codec
- avoid exposing `_encrypted` fields outside storage mappings

### Risk: scope creep into full identity persistence

Mitigation:

- persist only the four approved state domains
- continue treating users and sessions as external/non-persistent concerns

## Documentation Updates

Update project docs to reflect:

- PostgreSQL as the runtime persistence layer
- Alembic migration workflow
- local development setup for PostgreSQL
- any explicit seed/bootstrap commands

## Implementation Readiness

This design is intentionally scoped for one isolated development branch:

- storage abstraction is explicit
- service boundaries stay recognizable
- schema stays modest
- future KMS and Redis work remains possible without redoing this migration

The next step is to convert this design into a task-by-task implementation plan and execute it inside the `codex/pilot-hardening` worktree.
