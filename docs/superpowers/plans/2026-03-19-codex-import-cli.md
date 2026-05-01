# Codex Import CLI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local `routerctl codex import` workflow that launches Codex login in a temporary profile, extracts imported user OAuth credentials, and uploads them into the Router as a private upstream credential.

**Architecture:** Keep the implementation Python-native so it ships with the existing FastAPI project. The backend exposes a narrow import endpoint for `codex_chatgpt_oauth_imported`, while a small CLI creates a temporary `CODEX_HOME`, runs `codex login`, parses the file-backed login artifact, uploads the imported credential to the Router, and securely cleans up local state.

**Tech Stack:** Python 3.9+, FastAPI, httpx, subprocess/tempfile/pathlib, pytest

---

## Chunk 1: Backend Import Surface

### Task 1: Add failing backend tests for imported Codex credentials

**Files:**
- Modify: `tests/test_upstream_oauth.py`
- Test: `tests/test_upstream_oauth.py`

- [ ] **Step 1: Write the failing test**

```python
def test_member_can_import_codex_cli_credential() -> None:
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_upstream_oauth.py::test_member_can_import_codex_cli_credential`
Expected: FAIL because `/me/upstream-credentials/codex/import` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
@app.post("/me/upstream-credentials/codex/import")
async def import_codex_cli_credential(...):
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_upstream_oauth.py::test_member_can_import_codex_cli_credential`
Expected: PASS

### Task 2: Persist imported credentials with safe defaults

**Files:**
- Modify: `src/enterprise_llm_proxy/app.py`
- Modify: `src/enterprise_llm_proxy/services/credentials.py`
- Modify: `src/enterprise_llm_proxy/domain/credentials.py`
- Test: `tests/test_upstream_oauth.py`

- [ ] **Step 1: Write the failing test**

```python
def test_imported_codex_credentials_default_to_private_visibility() -> None:
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_upstream_oauth.py::test_imported_codex_credentials_default_to_private_visibility`
Expected: FAIL because imported credentials are not stored with the expected defaults.

- [ ] **Step 3: Write minimal implementation**

```python
credential_pool.create_credential(
    provider="openai",
    auth_kind="codex_chatgpt_oauth_imported",
    visibility=CredentialVisibility.PRIVATE,
    source="codex_cli_import",
    owner_principal_id=principal.user_id,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_upstream_oauth.py::test_imported_codex_credentials_default_to_private_visibility`
Expected: PASS

## Chunk 2: Local Import CLI

### Task 3: Add failing CLI tests for temp Codex login import

**Files:**
- Create: `src/enterprise_llm_proxy/cli.py`
- Create: `src/enterprise_llm_proxy/services/codex_cli_import.py`
- Create: `tests/test_codex_cli_import.py`
- Modify: `pyproject.toml`
- Test: `tests/test_codex_cli_import.py`

- [ ] **Step 1: Write the failing test**

```python
def test_codex_importer_reads_file_store_and_uploads_private_credential(tmp_path):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_codex_cli_import.py::test_codex_importer_reads_file_store_and_uploads_private_credential`
Expected: FAIL because the importer service and CLI do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
class CodexCliImporter:
    def run(self) -> ImportResult:
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_codex_cli_import.py::test_codex_importer_reads_file_store_and_uploads_private_credential`
Expected: PASS

### Task 4: Add device-auth fallback and cleanup guarantees

**Files:**
- Modify: `src/enterprise_llm_proxy/services/codex_cli_import.py`
- Test: `tests/test_codex_cli_import.py`

- [ ] **Step 1: Write the failing test**

```python
def test_codex_importer_falls_back_to_device_auth_and_cleans_tempdir(tmp_path):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_codex_cli_import.py::test_codex_importer_falls_back_to_device_auth_and_cleans_tempdir`
Expected: FAIL because fallback and cleanup are incomplete.

- [ ] **Step 3: Write minimal implementation**

```python
try:
    run_codex_login(["codex", "login"])
except ...
    run_codex_login(["codex", "login", "--device-auth"])
finally:
    shutil.rmtree(temp_home, ignore_errors=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_codex_cli_import.py::test_codex_importer_falls_back_to_device_auth_and_cleans_tempdir`
Expected: PASS

## Chunk 3: Operator Docs and End-to-End Verification

### Task 5: Document the new workflow and verify end-to-end behavior

**Files:**
- Modify: `README.md`
- Test: `tests/test_upstream_oauth.py`
- Test: `tests/test_codex_cli_import.py`

- [ ] **Step 1: Add usage docs**

```markdown
uv run routerctl codex import --router-base-url ...
```

- [ ] **Step 2: Run targeted test suites**

Run: `uv run pytest -q tests/test_upstream_oauth.py tests/test_codex_cli_import.py`
Expected: PASS

- [ ] **Step 3: Run full verification**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 4: Run CLI help verification**

Run: `uv run python -m enterprise_llm_proxy.cli --help`
Expected: exit 0 and show `codex import`
