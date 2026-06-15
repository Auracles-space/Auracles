# Local Test Isolation + Deliberate Dev↔Prod Switch — Design

**Date:** 2026-06-15
**Status:** Approved (brainstorming)

## Problem

`backend/app/core/config.py` loads `backend/.env` unconditionally
(`SettingsConfigDict(env_file=".env")`). Tests read all connection settings via
`get_settings()`. Several tests open real engines against
`settings.sync_database_url` and run schema/migration operations:

- `tests/unit/test_bootstrap_admin.py:23,50`
- `tests/unit/test_reputation_schema_foundation.py:42,86`
- `tests/unit/test_admin_schema_foundation.py:29`

Integration tests reach the DB through the `client` fixture → app → `get_db` →
async engine built from the same settings.

The local `backend/.env` was populated with **remote/production** values (Neon
Postgres, Upstash Redis, prod S3 buckets, real secrets). Consequences:

1. **Data-integrity risk (critical):** running `pytest` points the suite at
   production — tests can create/drop tables and write rows in prod.
2. Config placeholder-rejection tests fail locally because real (non-placeholder)
   secrets are present.

CLAUDE.md already states the intended design: *"`.env` local only, gitignored.
Secrets via AWS Secrets Manager (prod)."* Local `.env` is meant to hold dev
values only; prod secrets belong in the Render `auracles-secrets` group.

## Decisions (locked)

| # | Decision | Value |
|---|----------|-------|
| 1 | Need prod values locally? | **Yes** — must be able to point the local app at prod for debugging. Keep prod values in a separate gitignored file; switch deliberately. Tests always use dev. |
| 2 | Switch mechanism | **`ENV_FILE` env var read by config.** Default `.env` (dev). Prod via `ENV_FILE=.env.prod`. No shell sourcing, no per-secret juggling; works for app + Celery. |
| 3 | Test isolation strength | **Pin + guard (belt & suspenders).** conftest pins canonical local env before app import; a session guard hard-aborts pytest if the resolved DB/Redis host is not local. |

## Design

### 1. `ENV_FILE` switch (`config.py`)

Make the loaded env file dynamic; default unchanged.

```python
import os
...
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
```

- No `ENV_FILE` → loads `.env` (dev). Nothing accidental.
- Point local app/worker/beat at prod deliberately:
  `ENV_FILE=.env.prod uv run uvicorn app.main:app` (and the Celery commands).
- `get_settings()` is `lru_cache`d; `ENV_FILE` is read once at first settings
  construction, which is the desired process-lifetime behavior.

### 2. File layout + gitignore

- `backend/.env` → **restored to dev/local values** (mirror `.env.example`).
  Already gitignored (`.gitignore:12,26`).
- `backend/.env.prod` → the remote/prod values (moved out of `.env`).
  **New gitignore entry required** — the existing `.env` rule does not match
  `.env.prod`.
- `backend/.env.prod.example` → committed template (keys only, no secret
  values) documenting what `.env.prod` must contain.

gitignore additions:

```
.env.prod
backend/.env.prod
```

### 3. Test isolation — root `tests/conftest.py`

Two layers, both effective before `app.core.config` is imported.

**Pin.** At the top of `tests/conftest.py`, before importing `app`, set
`os.environ` to canonical local test values. `os.environ` outranks any
`env_file`, so tests ignore whatever `.env`/`.env.prod` contains:

```python
import os

os.environ.setdefault("ENVIRONMENT", "local")
os.environ["DATABASE_URL"] = "postgresql+asyncpg://auracles:secret@localhost:5432/auracles"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["SECRET_KEY"] = "dev-only-change-me"
os.environ["TOTP_ENCRYPTION_KEY"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
os.environ["PAYOUT_ACCOUNT_ENCRYPTION_KEY"] = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
os.environ["PARTNER_WEBHOOK_ENCRYPTION_KEY"] = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC="
os.environ["S3_ARTIFACTS_BUCKET"] = "auracles-artifacts-dev"
os.environ["S3_AVATARS_BUCKET"] = "auracles-avatars-dev"
os.environ["S3_REPORTS_BUCKET"] = "auracles-reports-dev"
os.environ["S3_THUMBNAILS_BUCKET"] = "auracles-thumbnails-dev"
```

The hardcoded values mirror CI's service-container env, so local and CI runs are
identical. (Pin uses direct assignment, not `setdefault`, for connection/secret
keys so a polluted shell or `.env` cannot win; `ENVIRONMENT` uses `setdefault`
so a deliberate non-local test mode is still possible if ever needed.)

**Guard.** A small importable function plus a session-autouse fixture that
hard-aborts if the resolved DB/Redis host is not local:

```python
# tests/_guard.py
from urllib.parse import urlsplit

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

def assert_local_datastores(database_url: str, redis_url: str) -> None:
    """Raise RuntimeError if either datastore host is not local."""
    for label, url in (("DATABASE_URL", database_url), ("REDIS_URL", redis_url)):
        host = urlsplit(url).hostname
        if host not in _LOCAL_HOSTS:
            raise RuntimeError(
                f"Refusing to run tests against non-local {label} host {host!r}."
            )
```

```python
# tests/conftest.py
import pytest
from app.core.config import get_settings
from tests._guard import assert_local_datastores

@pytest.fixture(scope="session", autouse=True)
def _guard_local_datastores() -> None:
    settings = get_settings()
    try:
        assert_local_datastores(settings.database_url, settings.redis_url)
    except RuntimeError as exc:
        pytest.exit(str(exc), returncode=1)
```

Guard logic lives in `tests/_guard.py` so it is unit-testable in isolation
rather than buried in a fixture. It catches `ENV_FILE=.env.prod pytest` and any
future env leak even though the pin should already force localhost.

## TDD coverage

Failing test first for each behavior.

- **`ENV_FILE` switch** — `tests/unit/test_config.py`:
  - `test_settings_loads_default_env_file_when_env_file_unset`: with `ENV_FILE`
    unset, the resolved `model_config["env_file"]` is `.env`.
  - `test_settings_honors_env_file_override`: write a tmp env file with a marker
    `DATABASE_URL`, set `ENV_FILE` to it (monkeypatch), construct `Settings`,
    assert it reads the marker. Validates the `os.getenv` wiring without
    depending on a real `.env.prod`.
- **conftest guard** — `tests/unit/test_test_guard.py`:
  - `test_guard_aborts_when_db_host_not_local`: `assert_local_datastores` with a
    non-local `DATABASE_URL` raises `RuntimeError`.
  - `test_guard_aborts_when_redis_host_not_local`: non-local `REDIS_URL` raises.
  - `test_guard_passes_for_localhost`: localhost URLs do not raise.
- **conftest pin** — verified by running the full suite while `backend/.env`
  still holds prod values: the suite must be green (pin overrides `.env`) and the
  guard must not trigger (localhost pinned).

## Execution order (slices)

1. `ENV_FILE` switch in `config.py` + the two config tests (red → green).
2. Restore `backend/.env` to dev values; create `backend/.env.prod` (move the
   remote values there); add `backend/.env.prod.example`; add gitignore entries.
3. Add `tests/_guard.py` + guard tests (red → green); wire pin block and
   `_guard_local_datastores` fixture into root `tests/conftest.py`.
4. Full-suite verify with a prod-valued `.env` on disk → all green, guard not
   triggered.
5. Docs: short note in `backend/README` — `pytest` always runs local;
   `ENV_FILE=.env.prod` points the app at prod.

## Edge cases

| Case | Handling |
|------|----------|
| `ENV_FILE` points at a missing file | pydantic-settings ignores a missing `env_file`, falling back to real env vars and defaults. App still boots; tests still pinned + guarded. |
| Stale shell env from a prior `source .env.prod` | conftest pin assigns connection/secret keys directly (not `setdefault`), overriding the shell; guard is the backstop. |
| CI | No `.env`; env vars set directly to localhost service containers. Pin is idempotent (same values); guard passes. No CI change. |
| Celery worker/beat against prod | Same `ENV_FILE=.env.prod` mechanism; documented in step 5. |

## Out of scope

- Secret rotation and Render `auracles-secrets` group management.
- Encryption-at-rest for `.env.prod` (gitignored plaintext, same posture as
  today's `.env`).
- Any change to CI workflow.
