# Framework Artifact Connectors — Phase A (Import Copy-In) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Contributors connect Google Drive (read-only), browse their files, and import one into a draft Framework as a normal Artifact — bytes copied into our S3 and fed through the existing `scan_artifact` pipeline.

**Architecture:** New `oauth_connections` table + `app/modules/integrations/` API module for connection lifecycle (connect / callback / revoke / list / browse). New `app/integrations/google_drive.py` provider client (httpx against fixed Google endpoints — no new dependency). Copy-in endpoint lives in the `frameworks` module and reuses the existing artifact creation + pipeline path. Phase A records **no** source binding on artifacts (that is Phase B); an imported artifact is indistinguishable from an uploaded one except for audit metadata.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, httpx + respx (tests), Fernet (cryptography), existing S3 storage helper, existing Celery pipeline.

**Spec:** `docs/superpowers/specs/2026-06-28-framework-artifact-connectors-design.md` (open questions resolved 2026-07-03: Drive only; new `oauth_connections`; provider-thumbnail preview is Phase B; this plan is Phase A only).

## Global Constraints

- Provider set v1: **Google Drive only**, but URL surface is provider-generic (`{provider}` path segment, value `google-drive`). Unknown provider → 404.
- OAuth scope: `https://www.googleapis.com/auth/drive.readonly` (read-only). Never request write scopes.
- Tokens encrypted at rest with a **new** Fernet key (`CONNECTOR_TOKEN_ENCRYPTION_KEY`), following the exact `totp_encryption_key` pattern in `app/core/config.py` + `app/core/security.py`. Tokens NEVER in responses, NEVER logged.
- All external fetches go only to fixed Google hosts (`accounts.google.com`, `oauth2.googleapis.com`, `www.googleapis.com`). Never fetch user-supplied URLs.
- Copy-in bytes always land in our S3 and always dispatch `scan_artifact` — pipeline is non-negotiable, no bypass.
- Audit (`write_audit`) every: connect, revoke, state-invalid callback, import. `target_type="oauth_connection"` for connection events, `"artifact"` for imports.
- Service transaction idiom (file-wide, matches organizations module): `if db.in_transaction(): await db.rollback()` then `async with db.begin():`; `IntegrityError` → 409.
- Loguru only, `module="integrations"` (or `"frameworks"` for copy-in), snake_case `action` tags.
- OpenAPI-first: contract updated + validated + frontend client regenerated before frontend work.
- TDD RED→GREEN per step. Run pytest from `backend/`. Whole-repo `uv run ruff check .` + `uv run mypy app` before every commit (CI lints tests too).
- Migration must round-trip: `alembic upgrade head` + `alembic downgrade -1`.
- Commit after each task. No `Co-Authored-By` trailer.
- One artifact-size budget: existing `ARTIFACT_MAX_TOTAL_SIZE` (500MB per framework) governs imports too.

## Existing interfaces you will reuse (verified against the codebase)

| Thing | Where | Signature |
|---|---|---|
| Fernet cipher pattern | `app/core/security.py:101-131` | `_totp_cipher() -> Fernet`, `encrypt_totp_secret(secret: str) -> str` |
| Signed cookie machinery | `app/core/cookies.py` | `_sign(encoded, settings)`, `_base64url_encode(...)`, `read_oauth_state_value(raw, settings)` pattern |
| PKCE/state helpers | `app/integrations/google_oauth.py` | `generate_pkce_pair() -> PkcePair(.verifier,.challenge)`, `generate_state() -> str`, `GOOGLE_AUTHORIZATION_ENDPOINT`, `GOOGLE_TOKEN_ENDPOINT` |
| Google login config | `app/core/config.py` | `google_client_id`, `google_client_secret: SecretStr`, `google_redirect_uri` — connector REUSES the same OAuth app, adds own redirect URI |
| Audit | `app/core/audit.py` | `write_audit(db, actor_id, action, target_type=..., target_id=..., metadata=...)` — does not commit |
| Rate limiting | `app/core/rate_limit.py` | `RateLimiter(namespace=..., limit=..., window=...)`, `await limiter.check(redis, key)` |
| S3 | `app/integrations/s3.py` | `s3.storage.upload_bytes(bucket, key, body, mime_type)`, `settings.s3_artifacts_bucket` |
| Artifact creation | `app/modules/frameworks/service.py:977-1060` | `_load_owned_framework`, `_require_editable_artifacts`, `ALLOWED_ARTIFACT_MIME_TYPES`, `ARTIFACT_MAX_TOTAL_SIZE`, `_extension_for_filename`, `_artifact_to_response` |
| Pipeline dispatch | `app/workers/tasks/artifacts.py` | `scan_artifact.delay(str(artifact.id))` |
| Model mixins | `app/shared/models/base.py` | `CreatedAtMixin`, `UpdatedAtMixin`; `Base` from `app.core.database` |
| Settings dependency | pattern in `app/modules/auth/router.py:68` | `AppSettings = Annotated[Settings, Depends(get_settings)]` |
| GDPR export touchpoint | `app/modules/gdpr/export_service.py` | bundle dict entry pattern, e.g. `"organization_memberships": await export_user_org_memberships(db, user_id=user_id)` |

Migration head at plan time: `2026_07_03_0061`. New revision: `2026_07_03_0062`.

---

### Task 1: Config key, encryption helpers, `OAuthConnection` model, migration

**Files:**
- Modify: `app/core/config.py` (new Fernet key + Drive redirect URI + dev-key guard)
- Modify: `app/core/security.py` (connector token cipher + encrypt/decrypt)
- Create: `app/modules/integrations/__init__.py`
- Create: `app/modules/integrations/models.py`
- Create: `migrations/versions/2026_07_03_0062_oauth_connections.py`
- Test: `tests/unit/test_security_connector_tokens.py`

**Interfaces:**
- Produces: `OAuthConnection` model (`oauth_connections` table), `encrypt_connector_token(token: str) -> str`, `decrypt_connector_token(encrypted: str) -> str`, settings fields `connector_token_encryption_key: SecretStr`, `google_drive_redirect_uri: str | None`.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for connector OAuth token encryption helpers."""

from app.core.security import decrypt_connector_token, encrypt_connector_token


def test_connector_token_round_trip() -> None:
    """Encrypting then decrypting a token returns the original value."""
    token = "ya29.a0AfB_example_access_token"
    encrypted = encrypt_connector_token(token)
    assert encrypted != token
    assert decrypt_connector_token(encrypted) == token


def test_connector_token_ciphertext_is_not_stable_plaintext() -> None:
    """Two encryptions of the same token never leak the plaintext."""
    token = "1//refresh_token_example"
    assert token not in encrypt_connector_token(token)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_security_connector_tokens.py -v`
Expected: FAIL — `ImportError: cannot import name 'encrypt_connector_token'`

- [ ] **Step 3: Implement config + security helpers**

In `app/core/config.py`, next to `DEV_TOTP_ENCRYPTION_KEY` (mirror that pattern exactly — constant, field, and the model validator that rejects the dev key outside local environments):

```python
DEV_CONNECTOR_TOKEN_ENCRYPTION_KEY = "ZGV2LWNvbm5lY3Rvci10b2tlbi0zMi1ieXRlcyEhISE="
```

Field on `Settings` (place beside the other encryption keys at `config.py:99-108`):

```python
    connector_token_encryption_key: SecretStr = Field(
        default=SecretStr(DEV_CONNECTOR_TOKEN_ENCRYPTION_KEY),
        alias="CONNECTOR_TOKEN_ENCRYPTION_KEY",
    )
    google_drive_redirect_uri: str | None = Field(
        default=None, alias="GOOGLE_DRIVE_REDIRECT_URI"
    )
```

Add a validator mirroring `config.py:216-222` (the TOTP dev-key guard) that rejects `DEV_CONNECTOR_TOKEN_ENCRYPTION_KEY` outside local environments — copy the existing validator's structure verbatim with the new field name.

In `app/core/security.py`, after `_partner_webhook_cipher` (line 115):

```python
def _connector_token_cipher() -> Fernet:
    """Build the Fernet cipher for connector OAuth tokens at rest."""
    key = get_settings().connector_token_encryption_key.get_secret_value()
    return Fernet(key.encode("utf-8"))


def encrypt_connector_token(token: str) -> str:
    """Encrypt a connector OAuth token for storage."""
    return _connector_token_cipher().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_connector_token(encrypted: str) -> str:
    """Decrypt a stored connector OAuth token."""
    return _connector_token_cipher().decrypt(encrypted.encode("utf-8")).decode("utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_security_connector_tokens.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Model**

`app/modules/integrations/models.py`:

```python
"""Integrations module ORM models.

Stores per-user OAuth connections to external file providers
(Google Drive in v1). Tokens are Fernet-encrypted at rest and are
never exposed through any schema or log.

Maps to: Framework Artifact Connectors design (Phase A).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin


class OAuthConnection(CreatedAtMixin, UpdatedAtMixin, Base):
    """A user's OAuth grant to an external file provider.

    One row per (user, provider): reconnecting replaces the stored
    tokens rather than adding a second connection.

    Attributes:
        provider: Provider key, e.g. ``google_drive``.
        provider_account_email: Display-only email of the connected account.
        access_token_encrypted: Fernet-encrypted OAuth access token.
        refresh_token_encrypted: Fernet-encrypted refresh token, if granted.
        token_expires_at: Access-token expiry used to refresh proactively.
        scopes: Space-separated granted scopes.
        status: ``active`` | ``revoked`` | ``reauth_required``.
    """

    __tablename__ = "oauth_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_oauth_connections_user_provider"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )
```

- [ ] **Step 6: Migration**

`migrations/versions/2026_07_03_0062_oauth_connections.py` — mirror the header style of `2026_07_03_0061_org_teams.py`:

```python
"""Add oauth_connections table for external file-provider grants.

Supports Framework Artifact Connectors Phase A: per-user Google Drive
connections with Fernet-encrypted tokens, feeding the import copy-in flow.

Revision ID: 2026_07_03_0062
Revises: 2026_07_03_0061
Create Date: 2026-07-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_03_0062"
down_revision: str | None = "2026_07_03_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_account_email", sa.String(255), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'active'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "provider", name="uq_oauth_connections_user_provider"),
    )
    op.create_index("ix_oauth_connections_user_id", "oauth_connections", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_connections_user_id", table_name="oauth_connections")
    op.drop_table("oauth_connections")
```

Check `CreatedAtMixin`/`UpdatedAtMixin` column defaults in `app/shared/models/base.py` and align the migration columns exactly (if the mixin uses a different server default, copy that).

- [ ] **Step 7: Round-trip the migration**

Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: all three succeed.

- [ ] **Step 8: Lint, type, commit**

Run: `cd backend && uv run ruff check . && uv run mypy app`
Expected: clean.

```bash
git add backend/app/core/config.py backend/app/core/security.py backend/app/modules/integrations/ backend/migrations/versions/2026_07_03_0062_oauth_connections.py backend/tests/unit/test_security_connector_tokens.py
git commit -m "Add oauth_connections model, connector token encryption, config keys"
```

---

### Task 2: Google Drive provider client

**Files:**
- Create: `app/integrations/google_drive.py`
- Test: `tests/unit/test_google_drive_integration.py`

**Interfaces:**
- Consumes: `generate_pkce_pair`, `generate_state`, `GOOGLE_AUTHORIZATION_ENDPOINT`, `GOOGLE_TOKEN_ENDPOINT` from `app/integrations/google_oauth.py`; settings `google_client_id`, `google_client_secret`, `google_drive_redirect_uri`.
- Produces (used by Tasks 3-5):
  - `DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"`
  - `class GoogleDriveError(RuntimeError)`, `class GoogleDriveAuthError(GoogleDriveError)` (401 / `invalid_grant` — caller marks connection `reauth_required`), `class DriveFileTooLargeError(GoogleDriveError)`
  - `@dataclass DriveTokens: access_token: str; refresh_token: str | None; expires_at: datetime`
  - `build_drive_authorization_url(*, state: str, code_challenge: str, settings: Settings) -> str` — adds `access_type=offline&prompt=consent`, scope `DRIVE_SCOPE`, redirect `google_drive_redirect_uri`
  - `async exchange_drive_code(*, code: str, verifier: str, settings: Settings) -> DriveTokens`
  - `async refresh_drive_tokens(*, refresh_token: str, settings: Settings) -> DriveTokens` (keeps the old refresh token when Google omits one)
  - `async revoke_drive_token(token: str) -> None` (best-effort POST `https://oauth2.googleapis.com/revoke`; swallow non-200 with a WARNING log)
  - `async fetch_drive_account_email(access_token: str) -> str | None` (GET `https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)`)
  - `async list_drive_files(*, access_token: str, query: str | None, page_token: str | None) -> dict` (GET `/drive/v3/files`, `q="trashed = false and mimeType != 'application/vnd.google-apps.folder'"` plus `and name contains '<escaped query>'` when given; `fields=nextPageToken,files(id,name,mimeType,size,modifiedTime,iconLink)`, `pageSize=25`, `orderBy=modifiedTime desc`; single-quote-escape the query string)
  - `async get_drive_file_metadata(*, access_token: str, file_id: str) -> dict` (`fields=id,name,mimeType,size`)
  - `async download_drive_file(*, access_token: str, file_id: str, export_mime: str | None, max_bytes: int) -> bytes` — `alt=media` for binary files, `/export?mimeType=` for Google-native; streams and raises `DriveFileTooLargeError` once accumulated bytes exceed `max_bytes`
  - `EXPORT_MIME_MAP: dict[str, tuple[str, str]]` mapping Google-native types to `(export_mime, extension)`:
    - `application/vnd.google-apps.document` → (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `docx`)
    - `application/vnd.google-apps.spreadsheet` → (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `xlsx`)
    - `application/vnd.google-apps.presentation` → (`application/vnd.openxmlformats-officedocument.presentationml.presentation`, `pptx`)

Implementation notes (follow `google_oauth.py` house style — module docstring, `_GOOGLE_TIMEOUT_SECONDS`-style constant, typed errors, httpx `AsyncClient`):
- All error paths raise `GoogleDriveError` (or the auth subclass); routers translate to 502/409. Never let raw httpx exceptions escape.
- 401 responses and token-endpoint `invalid_grant` → `GoogleDriveAuthError`.
- Never log tokens; log `action` + status codes only.

- [ ] **Step 1: Write failing tests** (respx, mirror `tests/unit/test_google_oauth.py` style)

Cover, each as its own test with a behavior docstring:
1. `build_drive_authorization_url` contains `access_type=offline`, `prompt=consent`, the Drive scope, `code_challenge`, and the Drive redirect URI.
2. `exchange_drive_code` posts `grant_type=authorization_code` + verifier and returns `DriveTokens` with computed `expires_at` (respx-mock token endpoint returning `{"access_token": "at", "refresh_token": "rt", "expires_in": 3600}`).
3. `refresh_drive_tokens` returns new access token and **retains the passed refresh token** when the response omits `refresh_token`.
4. `refresh_drive_tokens` raises `GoogleDriveAuthError` on `{"error": "invalid_grant"}` (400).
5. `list_drive_files` sends the folder-excluding `q` and returns the parsed dict; escapes single quotes in the search term.
6. `download_drive_file` uses `alt=media` for a binary file and the export URL for a Google-native mime.
7. `download_drive_file` raises `DriveFileTooLargeError` when the stream exceeds `max_bytes`.
8. `fetch_drive_account_email` returns `user.emailAddress`; returns `None` on error payload shape.

Run: `cd backend && uv run pytest tests/unit/test_google_drive_integration.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 2: Implement `app/integrations/google_drive.py`** to make all 8 pass.

- [ ] **Step 3: Run tests**

Run: `cd backend && uv run pytest tests/unit/test_google_drive_integration.py -v`
Expected: PASS (8 tests)

- [ ] **Step 4: Lint, type, commit**

```bash
git add backend/app/integrations/google_drive.py backend/tests/unit/test_google_drive_integration.py
git commit -m "Add Google Drive provider client (read-only OAuth, browse, download)"
```

---

### Task 3: Integrations API module — list / connect / callback / revoke

**Files:**
- Modify: `app/core/cookies.py` (connector state cookie helpers)
- Create: `app/modules/integrations/schemas.py`
- Create: `app/modules/integrations/service.py`
- Create: `app/modules/integrations/router.py`
- Modify: `app/main.py` (register `integrations_router`)
- Modify: `app/modules/gdpr/export_service.py` (bundle entry `connected_integrations`)
- Test: `tests/integration/test_integrations_endpoints.py`

**Interfaces:**
- Consumes: Task 1 model + crypto, Task 2 client.
- Produces (Tasks 4-5 rely on): `PROVIDERS = {"google-drive": "google_drive"}` (URL segment → stored value) in `service.py`; `async get_active_connection_with_fresh_token(db, *, user_id: UUID, provider: str | None = None, connection_id: UUID | None = None) -> tuple[OAuthConnection, str]` — exactly one selector must be given (`provider` for browse, `connection_id` for copy-in; raise `ValueError` if neither/both). Loads the user's connection (404 if absent/foreign, 409 `detail={"error_code": "reauth_required", ...}` if status `reauth_required`, 409 if `revoked`), refreshes the access token when `token_expires_at` is within 60s (persisting new encrypted token + expiry), and returns the decrypted access token. On `GoogleDriveAuthError` during refresh: set status `reauth_required`, commit, raise the 409.

**Endpoints** (router prefix `/integrations`, tag `Integrations`; every decorator carries `summary` + `description`):

| Method + path | Auth | Behavior |
|---|---|---|
| `GET /integrations/connectors` | any authenticated user | For each provider in `PROVIDERS`: `{provider, connected, status, account_email}` (from the user's row if any). |
| `POST /integrations/connectors/{provider}/connect` | `require_role("contributor")` | 404 unknown provider. Generate state + PKCE, set signed connector state cookie (carries `state`, `verifier`, `user_id`), return `{"authorization_url": ...}` (200). 503 if Google creds unconfigured (mirror `google_start`'s `GoogleOAuthError` handling). |
| `GET /integrations/connectors/{provider}/callback` | **public** (browser redirect; rate-limited) | Validate signed cookie + `state` query match → else 400 + `write_audit(action="connector_state_invalid", actor_id=None)` + WARNING log. Exchange code, fetch account email, upsert the user's `(user_id, provider)` row (encrypt tokens, status `active`), audit `connector_connected`, clear cookie, 302 to the frontend connections settings page (derive origin from `google_drive_redirect_uri`, path `/dashboard/settings?connector=google-drive&status=connected`; on failure same path with `status=error`). `error` query param from Google (user denied) → redirect with `status=denied`, no audit failure. |
| `DELETE /integrations/connectors/{provider}` | `require_role("contributor")` | 404 if no connection row. Best-effort `revoke_drive_token` on both tokens, set status `revoked`, null out both encrypted token columns, audit `connector_revoked`, 204. Idempotent: revoking a `revoked` connection returns 204. |

**Cookie helpers** in `app/core/cookies.py` (reuse `_sign` / `_base64url_encode` / the `read_oauth_state_value` verify-decode pattern; new constants `CONNECTOR_STATE_COOKIE_NAME = "auracles_connector_state"`, `CONNECTOR_STATE_MAX_AGE_SECONDS = 600`, cookie path `/v1/integrations`):
- `set_connector_state_cookie(response, *, state: str, verifier: str, user_id: str, settings) -> None`
- `read_connector_state_value(raw: str | None, settings) -> dict[str, object] | None`
- `clear_connector_state_cookie(response, settings) -> None`

**Rate limiting:** `CALLBACK_LIMITER = RateLimiter(namespace="connector_callback", limit=10, window=600)` keyed on client IP, checked first in the callback (it is unauthenticated).

**GDPR:** add to `app/modules/integrations/service.py`:

```python
async def export_user_connections(db: AsyncSession, *, user_id: UUID) -> list[dict[str, object]]:
    """GDPR export: the user's connector grants — metadata only, never tokens."""
```

returning `[{"provider", "account_email", "status", "connected_at"}]`, wired into the GDPR bundle as `"connected_integrations"` (same import direction as organizations: gdpr ← integrations only). Deletion needs no code: `ondelete="CASCADE"` covers it.

- [ ] **Step 1: Write failing integration tests** — `tests/integration/test_integrations_endpoints.py`, reusing the fixture pattern from `tests/integration/test_organizations_endpoints.py` (import `migrated_database`-style fixtures + `__all__` re-export; FakeRedis override from `tests/integration/test_auth_sessions.py`; respx for Google endpoints). Cover:
  1. `GET /v1/integrations/connectors` unauthenticated → 401.
  2. `GET /v1/integrations/connectors` → google-drive entry `connected: false`.
  3. `POST .../google-drive/connect` as operator-only user → 403; as contributor → 200 with `authorization_url` containing Drive scope, and a `Set-Cookie` for `auracles_connector_state`.
  4. `POST .../dropbox/connect` → 404.
  5. Callback with mismatched state → 400 and no connection row.
  6. Callback happy path (respx: token exchange + about) → 302, connection row exists with status `active`, tokens stored encrypted (assert stored value ≠ raw token and decrypts to it), list endpoint now shows `connected: true` with account email.
  7. Reconnect (second callback) → still exactly one row, tokens replaced.
  8. `DELETE .../google-drive` → 204, row status `revoked`, token columns null; second DELETE → 204.
  9. GDPR export bundle contains `connected_integrations` with the provider entry (call the export impl directly, mirroring `test_gdpr_exports.py`).

Run: `cd backend && uv run pytest tests/integration/test_integrations_endpoints.py -v`
Expected: FAIL — router not registered.

- [ ] **Step 2: Implement** schemas (`ConnectorStatusItem`, `ConnectorsResponse`, `ConnectorConnectResponse` — all `model_config = ConfigDict(from_attributes=True)` where reading ORM), service, router, cookie helpers, `main.py` registration (`integrations_router` after `health_router` import block, alphabetical placement), GDPR bundle entry.

- [ ] **Step 3: Run tests**

Run: `cd backend && uv run pytest tests/integration/test_integrations_endpoints.py tests/integration/test_gdpr_exports.py -v`
Expected: PASS.

- [ ] **Step 4: Lint, type, full suite, commit**

Run: `cd backend && uv run ruff check . && uv run mypy app && uv run pytest`
Expected: clean, all green.

```bash
git add backend/app/modules/integrations/ backend/app/core/cookies.py backend/app/main.py backend/app/modules/gdpr/export_service.py backend/tests/integration/test_integrations_endpoints.py
git commit -m "Add integrations module: Drive connect/callback/revoke/list + GDPR export entry"
```

---

### Task 4: Drive file browse endpoint

**Files:**
- Modify: `app/modules/integrations/router.py`, `service.py`, `schemas.py`
- Test: `tests/integration/test_integrations_files.py`

**Interfaces:**
- Consumes: `get_active_connection_with_fresh_token` (Task 3), `list_drive_files` (Task 2).
- Produces: `GET /v1/integrations/connectors/{provider}/files?query=&page_token=` → `ConnectorFilesResponse`.

**Schemas:**

```python
class ConnectorFileItem(BaseModel):
    """One importable file in the contributor's connected Drive."""

    id: str
    name: str
    mime_type: str
    size: int | None          # None for Google-native files (size unknown until export)
    modified_time: datetime | None
    icon_link: str | None
    importable: bool          # mime allowed directly or via EXPORT_MIME_MAP


class ConnectorFilesResponse(BaseModel):
    """One page of Drive files plus the pagination cursor."""

    files: list[ConnectorFileItem]
    next_page_token: str | None
```

**Behavior:** `require_role("contributor")`. 404 unknown provider / no connection. Uses the user's single `(user_id, provider)` connection (no connection_id param needed for browse). `importable` = `mime_type in ALLOWED_ARTIFACT_MIME_TYPES or mime_type in EXPORT_MIME_MAP`. Provider failure → 502 (`GoogleDriveError` caught, logged with context, never raw). Auth failure inside browse (401 from Drive after refresh attempt) → mark `reauth_required` + 409 `{"error_code": "reauth_required"}`.

- [ ] **Step 1: Failing tests:** happy page (respx Drive list → mapped fields incl. `importable` true for DOCX + Google-doc, false for e.g. `video/mp4`); `query` forwarded escaped; expired token → refresh called → new token persisted (assert stored encrypted token changed); refresh `invalid_grant` → 409 `reauth_required` + row status flipped; no connection → 404; Google 500 → 502.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Tests green:** `uv run pytest tests/integration/test_integrations_files.py -v`
- [ ] **Step 4: Lint, type, commit**

```bash
git commit -m "Add Drive file browse endpoint with on-demand token refresh"
```

---

### Task 5: Copy-in — `POST /v1/frameworks/{framework_id}/artifacts/from-connector`

**Files:**
- Modify: `app/modules/frameworks/schemas.py` (`ArtifactFromConnectorRequest`)
- Modify: `app/modules/frameworks/service.py` (`import_artifact_from_connector`)
- Modify: `app/modules/frameworks/router.py` (route)
- Test: `tests/integration/test_frameworks_from_connector.py`

**Interfaces:**
- Consumes: `get_active_connection_with_fresh_token` (import from `app.modules.integrations.service` — one-way dependency frameworks→integrations, no cycle), `get_drive_file_metadata`, `download_drive_file`, `EXPORT_MIME_MAP`, `DriveFileTooLargeError` (Task 2); existing frameworks internals (`_load_owned_framework`, `_require_editable_artifacts`, `ALLOWED_ARTIFACT_MIME_TYPES`, `ARTIFACT_MAX_TOTAL_SIZE`, `_extension_for_filename`, `_artifact_to_response`, `s3.storage.upload_bytes`, `scan_artifact`).

**Request schema:**

```python
class ArtifactFromConnectorRequest(BaseModel):
    """Import a connected-source file as a new draft Artifact."""

    connection_id: UUID
    file_id: str = Field(min_length=1, max_length=256)
```

**Service behavior** (`import_artifact_from_connector(db, contributor, framework_id, payload) -> ArtifactResponse`), mirroring `request_artifact_upload_url` + `confirm_artifact_upload` semantics:
1. `_load_owned_framework`, `_require_editable_artifacts`; `pipeline_passed` framework drops back to `draft` exactly as `request_artifact_upload_url` does (`service.py:986-988`).
2. Resolve connection + fresh token via `get_active_connection_with_fresh_token` (its 404/409 pass through).
3. `get_drive_file_metadata`. Effective mime + filename: Google-native mime → `EXPORT_MIME_MAP` gives `(export_mime, ext)`, filename becomes `f"{name}.{ext}"`; binary mime used as-is. Effective mime not in `ALLOWED_ARTIFACT_MIME_TYPES` → 415 "Unsupported artifact MIME type." (same copy as upload path).
4. Size budget: `remaining = ARTIFACT_MAX_TOTAL_SIZE - sum(existing artifact sizes)` (same query as `service.py:995-1005`). Known metadata size > remaining → 413 "Framework artifacts exceed the 500MB limit." Unknown size (export) → enforce during download via `max_bytes=remaining`.
5. `download_drive_file(..., max_bytes=remaining)`; `DriveFileTooLargeError` → 413; `GoogleDriveAuthError` → 409 `reauth_required` (mark connection); other `GoogleDriveError` → 502 with context log.
6. Create `Artifact` row (same `file_key` scheme `frameworks/{framework_id}/artifacts/{artifact_id}.{ext}`, `file_size=len(bytes)`, `processing_status="processing"`), `s3.storage.upload_bytes(settings.s3_artifacts_bucket, file_key, body, effective_mime)`, `write_audit(action="artifact_uploaded", target_type="artifact", target_id=artifact.id, metadata={"framework_id": ..., "source": "google_drive", "connection_id": ..., "external_file_id": payload.file_id})`, commit, `scan_artifact.delay(str(artifact.id))`, INFO log `artifact_import_completed` (log `artifact_id`, never file contents or tokens).
7. Return `_artifact_to_response(artifact)`.

**Router:** `POST /{framework_id}/artifacts/from-connector`, contributor-gated like the sibling artifact routes, OpenAPI `summary="Import an Artifact from a connected source"` + description.

- [ ] **Step 1: Failing tests** (respx for Drive; monkeypatch `s3.storage.upload_bytes` + capture; monkeypatch `scan_artifact.delay`): happy path binary file (artifact row created, bytes uploaded, scan dispatched, audit metadata has `source: "google_drive"`); Google-native doc exported with mapped mime + `.docx` name; disallowed mime → 415, no artifact row; oversize known metadata → 413 before download; `DriveFileTooLargeError` mid-download → 413, no artifact row, no S3 upload; foreign connection_id → 404; non-owner framework → 404; published framework → the `_require_editable_artifacts` error passes through.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Tests green** + full suite: `cd backend && uv run pytest`
- [ ] **Step 4: Lint, type, commit**

```bash
git commit -m "Add from-connector artifact import feeding the standard pipeline"
```

---

### Task 6: OpenAPI contract + frontend client regeneration

**Files:**
- Modify: `contracts/openapi.yaml`
- Modify: `frontend/src/lib/generated/*` (regenerated)

- [ ] **Step 1:** Regenerate the contract from the app (established practice: dump `app.openapi()` to YAML the same way the Organizations Core Task 13 did), confirm the new paths present: `/v1/integrations/connectors`, `.../{provider}/connect`, `.../{provider}/callback`, `.../{provider}` (DELETE), `.../{provider}/files`, `/v1/frameworks/{framework_id}/artifacts/from-connector`.
- [ ] **Step 2:** Validate: `uv run python -c "from openapi_spec_validator import validate; import yaml; validate(yaml.safe_load(open('../contracts/openapi.yaml')))"` → no output.
- [ ] **Step 3:** Regenerate frontend client (existing hey-api codegen script in `frontend/package.json`).
- [ ] **Step 4:** `cd frontend && npx tsc --noEmit` → error count identical to baseline (9, all in `attestation-workspaces.tsx` + `admin-config-panel.tsx`); zero new.
- [ ] **Step 5: Commit**

```bash
git add contracts/openapi.yaml frontend/src/lib/generated/
git commit -m "Update OpenAPI contract and frontend client for connector endpoints"
```

---

### Task 7: Frontend UI (implementer designs the UI itself)

> Same handoff style as `2026-07-03-organizations-frontend.md`: this task defines WHAT, the implementer owns the design. Invoke the `frontend-design` skill; Brand Book is the visual source of truth. Mobile-first, 44px targets, verified at 375px. Generated client only. Component tests (vitest + msw), zero new typecheck errors.

**Surfaces:**

1. **Connected apps** (in settings area): list providers from `GET /v1/integrations/connectors` — connected state, account email, connect button (calls `POST .../connect`, then `window.location.assign(authorization_url)`), disconnect with confirm (`DELETE`). Handle the callback landing query params (`?connector=google-drive&status=connected|error|denied`) with a clear confirmation/failure state. A `reauth_required` connection shows a "Reconnect" treatment, not a silent failure.
2. **Import from Drive** in the contributor artifact-upload area (framework editor): entry point alongside the existing upload control; search-driven picker (list from `GET .../files` with `query` debounce + `next_page_token` "load more"); non-importable files visibly disabled; selecting a file → `POST /v1/frameworks/{id}/artifacts/from-connector` → merge into the existing artifact processing-status polling UI (import lands as a normal processing artifact). No connection yet → inline prompt linking to Connected apps (or inline connect). 409 `reauth_required` → reconnect prompt; 413/415 → inline errors with the backend detail.

**Tests:** component tests for connectors list (empty/connected/reauth), picker (search, pagination, disabled non-importable, import success merges into artifact list, 409/413/415 error rendering).

- [ ] Build, test, verify at 375px, commit:

```bash
git commit -m "Add Connected apps settings and Drive import picker"
```

---

## Verification (whole plan)

- `cd backend && uv run pytest` — full suite green.
- `uv run ruff check .` + `uv run mypy app` — clean.
- Migration round-trips.
- Contract validates; client regen idempotent; typecheck delta zero-new.
- Manual sandbox pass with a Google test OAuth client: connect → browse → import a Doc + a PDF → pipeline processes both → revoke → browse returns 409/404 path.
- Grep gate: no token value appears in any log call or response schema (`rg -n "access_token" backend/app/modules/integrations backend/app/integrations/google_drive.py` — every hit is storage/transport, none in logger calls or response models).

## Risks (flagged)

- **Google restricted scope.** `drive.readonly` is a restricted scope: production OAuth consent requires Google verification and possibly a CASA security assessment. Dev/test users work immediately (testing mode, 100-user cap). Budget verification lead time before public launch. Alternative (`drive.file` + Google Picker) avoids verification but deviates from the approved spec's server-side browse — architect's call if verification cost is unacceptable.
- **Token security.** Encrypted at rest, never logged/returned — enforced by tests + the grep gate; reviewer must re-check.
- **Scope creep toward live-mirror.** Phase A stores no artifact source binding by design. Any "keep it synced" ask is Phase B/C — do not build it here.
