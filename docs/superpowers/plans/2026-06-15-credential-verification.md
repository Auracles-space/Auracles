# Credential Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manual, Admin-driven verification to user-owned Credentials — a `unverified → pending → verified | rejected` lifecycle with an admin review queue and verified-only public display.

**Architecture:** Extend the existing `Credential` model (`app/modules/attestation/`) with verification state + metadata in one Alembic migration. State-machine logic lives in `credential_service.py`; the owner gets a `submit` endpoint on the existing attestation router (`/v1/credentials/*`), admins get a review queue on the admin router (`/v1/admin/credentials/*`). Verified credentials surface on the public contributor profile via the explore module. RBAC is enforced by FastAPI dependencies (`require_role("admin")`, owner checks in-service); backend is the authoritative gate.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, Alembic, Postgres ENUMs, pytest + httpx AsyncClient, loguru, `dispatch_project_notification` Celery task.

**Spec:** `docs/superpowers/specs/2026-06-15-credential-verification-design.md`

---

## File structure

| File | Responsibility | Action |
|------|----------------|--------|
| `backend/migrations/versions/2026_06_15_0028_credential_verification.py` | 2 enums + 9 columns + index on `credentials` | Create |
| `backend/app/modules/attestation/models.py` | `Credential` ORM gains columns + enum refs | Modify |
| `backend/app/modules/attestation/schemas.py` | new fields on create/update + `CredentialResponse`; new submit/verify/reject + admin-queue + public schemas | Modify |
| `backend/app/modules/attestation/credential_service.py` | submit / verify / reject / edit-reset state logic + notify | Modify |
| `backend/app/modules/attestation/router.py` | owner `POST /credentials/{id}/submit` | Modify |
| `backend/app/modules/admin/router.py` | `GET /admin/credentials`, `POST /admin/credentials/{id}/verify`, `POST /admin/credentials/{id}/reject` | Modify |
| `backend/app/modules/admin/schemas.py` | admin credential queue + reject request schemas | Modify |
| `backend/app/modules/explore/service.py` + `schemas.py` + `router.py` | verified credentials on contributor profile | Modify |
| `contracts/openapi.yaml` | endpoint + schema sync | Modify |
| `frontend/src/lib/generated/types.gen.ts` | regenerated client types | Modify (regen) |
| `backend/tests/unit/modules/test_credential_verification_service.py` | service state-machine unit tests | Create |
| `backend/tests/integration/test_credential_verification.py` | owner + admin endpoint integration tests | Create |
| `backend/tests/integration/test_explore_contributor_credentials.py` | public-exposure leak test | Create |

**Routing facts (verified):** attestation router has no prefix → owner credential routes are `/v1/credentials/*`. Admin router prefix `/admin` → `/v1/admin/credentials/*`. Explore prefix `/explore` → `/v1/explore/contributors/{id}`.

**Shared test helpers** (copy the patterns already in `backend/tests/integration/test_credentials.py`): `create_user(email, roles)`, `auth_headers(user_id, roles)`, the `migrated_database` and `credential_context` fixtures, `reset_credential_state()`.

---

## Task 1: Schema migration + model columns

**Files:**
- Create: `backend/migrations/versions/2026_06_15_0028_credential_verification.py`
- Modify: `backend/app/modules/attestation/models.py`
- Test: `backend/tests/integration/test_credential_verification.py` (migration round-trip + column presence)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_credential_verification.py` with:

```python
"""Integration tests for manual Credential verification (Admin-driven)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, inspect, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.attestation.models import AttestationUploadSession, Credential
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for routes that do not use Redis directly."""


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure credential tables exist for endpoint tests."""
    sync_engine = create_engine(app.state.settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


async def reset_credential_state() -> None:
    """Remove credential test rows in dependency order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(Credential))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
async def credential_context() -> AsyncIterator[FakeRedis]:
    """Reset credential/auth state and install a Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    await reset_credential_state()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await reset_credential_state()
        await engine.dispose()


async def create_user(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved role rows."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            for role in roles:
                session.add(
                    UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC))
                )
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


def test_credentials_table_has_verification_columns(migrated_database: None) -> None:
    """Migration adds verification + metadata columns to credentials."""
    del migrated_database
    sync_engine = create_engine(app.state.settings.sync_database_url)
    try:
        columns = {col["name"] for col in inspect(sync_engine).get_columns("credentials")}
    finally:
        sync_engine.dispose()
    assert {
        "verification_status",
        "credential_type",
        "verification_url",
        "reference_number",
        "issuer_type",
        "submitted_at",
        "verified_at",
        "reviewed_by",
        "rejection_reason",
    } <= columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py::test_credentials_table_has_verification_columns -v`
Expected: FAIL — columns absent.

- [ ] **Step 3: Write the migration**

Create `backend/migrations/versions/2026_06_15_0028_credential_verification.py`:

```python
"""Add manual verification fields to credentials.

Supports the credential-verification feature: a manual, Admin-driven
unverified->pending->verified|rejected lifecycle plus issuer metadata used by
reviewers. Maps to FR-ATT-003 / FR-SET-002 and the full-spec Credential Registry.

Revision ID: 2026_06_15_0028
Revises: 2026_06_13_0027
Create Date: 2026-06-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_15_0028"
down_revision: str | Sequence[str] | None = "2026_06_13_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_ENUM = postgresql.ENUM(
    "unverified",
    "pending",
    "verified",
    "rejected",
    name="credential_verification_status_enum",
    create_type=False,
)
_ISSUER_TYPE_ENUM = postgresql.ENUM(
    "institution",
    "organisation",
    "government",
    "association",
    name="credential_issuer_type_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create verification enums and add columns to credentials."""
    bind = op.get_bind()
    _STATUS_ENUM.create(bind, checkfirst=True)
    _ISSUER_TYPE_ENUM.create(bind, checkfirst=True)
    op.add_column(
        "credentials",
        sa.Column(
            "verification_status",
            _STATUS_ENUM,
            nullable=False,
            server_default="unverified",
        ),
    )
    op.add_column("credentials", sa.Column("credential_type", sa.Text(), nullable=True))
    op.add_column("credentials", sa.Column("verification_url", sa.Text(), nullable=True))
    op.add_column("credentials", sa.Column("reference_number", sa.Text(), nullable=True))
    op.add_column(
        "credentials", sa.Column("issuer_type", _ISSUER_TYPE_ENUM, nullable=True)
    )
    op.add_column(
        "credentials",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "credentials",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "credentials",
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "credentials", sa.Column("rejection_reason", sa.Text(), nullable=True)
    )
    op.create_foreign_key(
        "fk_credentials_reviewed_by_users",
        "credentials",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_credentials_verification_status",
        "credentials",
        ["verification_status"],
    )


def downgrade() -> None:
    """Drop verification columns and enums from credentials."""
    bind = op.get_bind()
    op.drop_index("idx_credentials_verification_status", table_name="credentials")
    op.drop_constraint(
        "fk_credentials_reviewed_by_users", "credentials", type_="foreignkey"
    )
    for column in (
        "rejection_reason",
        "reviewed_by",
        "verified_at",
        "submitted_at",
        "issuer_type",
        "reference_number",
        "verification_url",
        "credential_type",
        "verification_status",
    ):
        op.drop_column("credentials", column)
    _ISSUER_TYPE_ENUM.drop(bind, checkfirst=True)
    _STATUS_ENUM.drop(bind, checkfirst=True)
```

- [ ] **Step 4: Add columns + enum refs to the model**

In `backend/app/modules/attestation/models.py`, after the existing enum definitions (near `ATTESTATION_UPLOAD_SCAN_STATUS_ENUM`), add:

```python
CREDENTIAL_VERIFICATION_STATUS_ENUM = ENUM(
    "unverified",
    "pending",
    "verified",
    "rejected",
    name="credential_verification_status_enum",
    create_type=False,
)
CREDENTIAL_ISSUER_TYPE_ENUM = ENUM(
    "institution",
    "organisation",
    "government",
    "association",
    name="credential_issuer_type_enum",
    create_type=False,
)
```

Then inside `class Credential`, after `evidence_file_keys`, add:

```python
    verification_status: Mapped[str] = mapped_column(
        CREDENTIAL_VERIFICATION_STATUS_ENUM,
        nullable=False,
        server_default="unverified",
    )
    credential_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    issuer_type: Mapped[str | None] = mapped_column(
        CREDENTIAL_ISSUER_TYPE_ENUM, nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 5: Run the column test + migration round-trip**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py::test_credentials_table_has_verification_columns -v`
Expected: PASS.

Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: all three succeed, no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/2026_06_15_0028_credential_verification.py backend/app/modules/attestation/models.py backend/tests/integration/test_credential_verification.py
git commit -m "feat(credentials): verification schema — enums, columns, migration"
```

---

## Task 2: Schemas — new fields + verification request/response shapes

**Files:**
- Modify: `backend/app/modules/attestation/schemas.py`
- Test: `backend/tests/unit/modules/test_credential_verification_service.py` (schema validation portion)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/modules/test_credential_verification_service.py` with the schema tests first:

```python
"""Unit tests for Credential verification schemas and service state machine."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.attestation.schemas import (
    AdminCredentialRejectRequest,
    CredentialCreateRequest,
)


def test_create_request_accepts_new_metadata_fields() -> None:
    """Create request accepts credential_type, verification_url, reference, issuer_type."""
    request = CredentialCreateRequest(
        title="PMP",
        issuer="PMI",
        issued_date="2024-01-01",
        credential_type="PMP",
        verification_url="https://verify.pmi.org/x",
        reference_number="PMP-12345",
        issuer_type="association",
    )
    assert request.credential_type == "PMP"
    assert request.issuer_type == "association"


def test_create_request_rejects_unknown_issuer_type() -> None:
    """issuer_type is constrained to the four-value taxonomy."""
    with pytest.raises(ValidationError):
        CredentialCreateRequest(
            title="PMP",
            issuer="PMI",
            issued_date="2024-01-01",
            issuer_type="bank",
        )


def test_reject_request_requires_non_empty_reason() -> None:
    """Admin reject must carry a reason."""
    with pytest.raises(ValidationError):
        AdminCredentialRejectRequest(reason="")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_credential_verification_service.py -v`
Expected: FAIL — `AdminCredentialRejectRequest` and the new fields do not exist.

- [ ] **Step 3: Extend `CredentialCreateRequest` and `CredentialUpdateRequest`**

In `backend/app/modules/attestation/schemas.py`, add `Literal` to the typing import if missing (it is already imported). Replace the `CredentialCreateRequest` class body additions and `CredentialUpdateRequest` additions:

```python
IssuerType = Literal["institution", "organisation", "government", "association"]
```

Add to `CredentialCreateRequest` (after `expires_date`, before the validator):

```python
    credential_type: str | None = Field(default=None, max_length=255)
    verification_url: str | None = Field(default=None, max_length=2048)
    reference_number: str | None = Field(default=None, max_length=255)
    issuer_type: IssuerType | None = None
```

Add the same four fields to `CredentialUpdateRequest`.

- [ ] **Step 4: Extend `CredentialResponse` and add verification schemas**

In `CredentialResponse`, after `evidence_file_keys`, add:

```python
    credential_type: str | None
    verification_url: str | None
    reference_number: str | None
    issuer_type: str | None
    verification_status: str
    submitted_at: datetime | None
    verified_at: datetime | None
    reviewed_by: UUID | None
    rejection_reason: str | None
    expired: bool
```

Then append new schemas at the end of the file:

```python
class AdminCredentialRejectRequest(BaseModel):
    """Admin request body for rejecting a pending Credential."""

    reason: str = Field(min_length=1, max_length=4000)


class AdminCredentialResponse(BaseModel):
    """Credential detail for the admin review queue (includes review evidence)."""

    id: UUID
    user_id: UUID
    title: str
    issuer: str
    issued_date: date
    expires_date: date | None
    credential_type: str | None
    verification_url: str | None
    reference_number: str | None
    issuer_type: str | None
    evidence_file_keys: list[str]
    verification_status: str
    submitted_at: datetime | None
    verified_at: datetime | None
    reviewed_by: UUID | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminCredentialsResponse(BaseModel):
    """Paginated admin credential review queue."""

    credentials: list[AdminCredentialResponse]


class PublicCredentialResponse(BaseModel):
    """Verified Credential fields safe for public profile display.

    Never exposes evidence keys, verification URL, reference number, or review
    metadata — anti-gaming and PII protection.
    """

    title: str
    issuer: str
    credential_type: str | None
    issued_date: date
    expires_date: date | None
    expired: bool
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend && uv run pytest tests/unit/modules/test_credential_verification_service.py -v`
Expected: PASS (the 3 schema tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/attestation/schemas.py backend/tests/unit/modules/test_credential_verification_service.py
git commit -m "feat(credentials): verification schemas — metadata fields, admin + public shapes"
```

---

## Task 3: Service — submit_credential

**Files:**
- Modify: `backend/app/modules/attestation/credential_service.py`
- Test: `backend/tests/unit/modules/test_credential_verification_service.py`

Service tests use an in-memory-ish async session against the test DB the same way other unit/modules tests do. Use the integration-style DB helpers if the existing unit module tests need a session; here we test the service directly with a real `AsyncSession` from `async_session_factory`. Add these imports to the test file:

```python
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import HTTPException

from app.core.database import async_session_factory
from app.modules.attestation import credential_service
from app.modules.attestation.models import Credential
from app.modules.auth.models import User
```

Add a helper in the test file:

```python
async def _make_user_with_credential(**credential_kwargs) -> tuple[User, Credential]:
    """Persist a user and one owned credential, returning detached-safe copies."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"cred-{datetime.now(UTC).timestamp()}@auracles.space",
                password_hash="x",
                display_name="Cred Owner",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            credential = Credential(
                user_id=user.id,
                title="PMP",
                issuer="PMI",
                issued_date=date(2024, 1, 1),
                **credential_kwargs,
            )
            session.add(credential)
            await session.flush()
            return user, credential
```

(These DB-backed service tests require the `migrated_database` fixture; import it or rely on the integration fixture. For simplicity place service DB tests that need tables in the integration file if the unit suite has no DB. Check `tests/unit/modules/` neighbors — if they hit the DB, follow their fixture; otherwise put DB-backed service assertions in the integration file created in Task 1.)

- [ ] **Step 1: Write the failing test**

Add to the integration file `test_credential_verification.py` (it already has the `migrated_database`/`credential_context` fixtures and DB helpers):

```python
from app.modules.attestation import credential_service
from app.modules.attestation.models import Credential
from fastapi import HTTPException
from datetime import date


async def _seed_credential(user_id: UUID, **kwargs) -> UUID:
    async with async_session_factory() as session:
        async with session.begin():
            credential = Credential(
                user_id=user_id,
                title=kwargs.pop("title", "PMP"),
                issuer=kwargs.pop("issuer", "PMI"),
                issued_date=kwargs.pop("issued_date", date(2024, 1, 1)),
                **kwargs,
            )
            session.add(credential)
            await session.flush()
            return credential.id


async def test_submit_requires_evidence(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """Submitting a credential with no evidence/url/reference is rejected 422."""
    del migrated_database, credential_context
    user_id = await create_user("submit-noev@auracles.space", ["contributor"])
    credential_id = await _seed_credential(user_id)
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        with pytest.raises(HTTPException) as exc:
            await credential_service.submit_credential(
                db=session, user=user, credential_id=credential_id
            )
    assert exc.value.status_code == 422


async def test_submit_transitions_to_pending(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """A credential with a reference number can be submitted -> pending."""
    del migrated_database, credential_context
    user_id = await create_user("submit-ok@auracles.space", ["contributor"])
    credential_id = await _seed_credential(user_id, reference_number="PMP-1")
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        result = await credential_service.submit_credential(
            db=session, user=user, credential_id=credential_id
        )
    assert result.verification_status == "pending"
    assert result.submitted_at is not None


async def test_submit_blocked_when_already_verified(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """Submitting an already-verified credential raises 422."""
    del migrated_database, credential_context
    user_id = await create_user("submit-verified@auracles.space", ["contributor"])
    credential_id = await _seed_credential(
        user_id, reference_number="PMP-1", verification_status="verified"
    )
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        with pytest.raises(HTTPException) as exc:
            await credential_service.submit_credential(
                db=session, user=user, credential_id=credential_id
            )
    assert exc.value.status_code == 422
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py -k submit -v`
Expected: FAIL — `submit_credential` does not exist.

- [ ] **Step 3: Implement `submit_credential`**

In `backend/app/modules/attestation/credential_service.py`, add near the top after imports:

```python
_SUBMITTABLE_STATUSES = {"unverified", "rejected"}
```

Add the function:

```python
async def submit_credential(
    db: AsyncSession,
    user: User,
    credential_id: UUID,
) -> Credential:
    """Submit an owned Credential for manual Admin verification.

    Transitions ``unverified``/``rejected`` to ``pending``. Requires at least
    one piece of reviewable evidence (an uploaded file, a verification URL, or a
    reference number) so an Admin has something to check.

    Raises:
        HTTPException(404): Credential missing or not owned by the user.
        HTTPException(422): Invalid state transition or no reviewable evidence.
    """
    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        credential = await _load_owned_credential_for_update(
            db=db, user_id=user_id, credential_id=credential_id
        )
        if credential.verification_status not in _SUBMITTABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Credential cannot be submitted from its current state.",
            )
        has_evidence = bool(
            credential.evidence_file_keys
            or credential.verification_url
            or credential.reference_number
        )
        if not has_evidence:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Attach evidence, a verification URL, or a reference number "
                "before submitting.",
            )
        credential.verification_status = "pending"
        credential.submitted_at = datetime.now(UTC)
        credential.rejection_reason = None
        await write_audit(
            db=db,
            actor_id=user_id,
            action="credential_submitted",
            target_type="credential",
            target_id=credential.id,
            metadata={"title": credential.title},
        )
        await db.flush()
        await db.refresh(credential)
    return credential
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py -k submit -v`
Expected: PASS (3 submit tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/attestation/credential_service.py backend/tests/integration/test_credential_verification.py
git commit -m "feat(credentials): submit_credential lifecycle with evidence gate"
```

---

## Task 4: Service — verify_credential + reject_credential (admin) + notify

**Files:**
- Modify: `backend/app/modules/attestation/credential_service.py`
- Test: `backend/tests/integration/test_credential_verification.py`

- [ ] **Step 1: Write the failing test**

Add to `test_credential_verification.py`:

```python
async def test_verify_only_from_pending(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """verify_credential promotes pending -> verified and stamps reviewer."""
    del migrated_database, credential_context
    admin_id = await create_user("verify-admin@auracles.space", ["admin"])
    owner_id = await create_user("verify-owner@auracles.space", ["contributor"])
    credential_id = await _seed_credential(
        owner_id, reference_number="PMP-1", verification_status="pending"
    )
    async with async_session_factory() as session:
        result = await credential_service.verify_credential(
            db=session, admin_id=admin_id, credential_id=credential_id
        )
    assert result.verification_status == "verified"
    assert result.verified_at is not None
    assert result.reviewed_by == admin_id


async def test_verify_rejects_non_pending(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """Verifying a non-pending credential raises 422."""
    del migrated_database, credential_context
    admin_id = await create_user("verify-admin2@auracles.space", ["admin"])
    owner_id = await create_user("verify-owner2@auracles.space", ["contributor"])
    credential_id = await _seed_credential(owner_id, reference_number="PMP-1")
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await credential_service.verify_credential(
                db=session, admin_id=admin_id, credential_id=credential_id
            )
    assert exc.value.status_code == 422


async def test_reject_requires_pending_and_sets_reason(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """reject_credential moves pending -> rejected and stores the reason."""
    del migrated_database, credential_context
    admin_id = await create_user("reject-admin@auracles.space", ["admin"])
    owner_id = await create_user("reject-owner@auracles.space", ["contributor"])
    credential_id = await _seed_credential(
        owner_id, reference_number="PMP-1", verification_status="pending"
    )
    async with async_session_factory() as session:
        result = await credential_service.reject_credential(
            db=session,
            admin_id=admin_id,
            credential_id=credential_id,
            reason="Issuer could not confirm.",
        )
    assert result.verification_status == "rejected"
    assert result.rejection_reason == "Issuer could not confirm."
    assert result.reviewed_by == admin_id
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py -k "verify or reject" -v`
Expected: FAIL — functions missing.

- [ ] **Step 3: Implement verify/reject + notification helper**

In `credential_service.py`, add the import near the others:

```python
from app.workers.tasks.project_notifications import dispatch_project_notification
```

Add a notification helper and the two admin functions:

```python
def _notify_credential_decision(
    *, user_id: UUID, credential: Credential, verified: bool
) -> None:
    """Queue a durable notification telling the owner of a review decision."""
    notification_type = (
        "credential_verified" if verified else "credential_rejected"
    )
    title = "Credential verified" if verified else "Credential needs attention"
    body = (
        "Your credential has been verified."
        if verified
        else "Your credential was not verified. Review the feedback and resubmit."
    )
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type=notification_type,
            title=title,
            body=body,
            payload={
                "credential_id": str(credential.id),
                "status": credential.verification_status,
            },
            link="/settings/credentials",
            dedupe_key=f"{notification_type}:{credential.id}",
        )
    except Exception as exc:  # pragma: no cover - dispatch best-effort
        logger.bind(
            module="attestation",
            action="notify_credential_decision",
            user_id=user_id,
            credential_id=credential.id,
        ).error("notification_dispatch_failed", error=str(exc))


async def _load_credential_for_review(
    db: AsyncSession, credential_id: UUID
) -> Credential:
    """Load any credential by id with a row lock or raise 404 (admin scope)."""
    credential = await db.scalar(
        select(Credential).where(Credential.id == credential_id).with_for_update()
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found."
        )
    return credential


async def verify_credential(
    db: AsyncSession, admin_id: UUID, credential_id: UUID
) -> Credential:
    """Mark a pending Credential verified (Admin action).

    Raises:
        HTTPException(404): Credential not found.
        HTTPException(422): Credential is not pending.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        credential = await _load_credential_for_review(db, credential_id)
        if credential.verification_status != "pending":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only pending credentials can be verified.",
            )
        credential.verification_status = "verified"
        credential.verified_at = datetime.now(UTC)
        credential.reviewed_by = admin_id
        credential.rejection_reason = None
        owner_id = credential.user_id
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="credential_verified",
            target_type="credential",
            target_id=credential.id,
            metadata={"owner_id": str(owner_id)},
        )
        await db.flush()
        await db.refresh(credential)
    _notify_credential_decision(user_id=owner_id, credential=credential, verified=True)
    return credential


async def reject_credential(
    db: AsyncSession, admin_id: UUID, credential_id: UUID, reason: str
) -> Credential:
    """Reject a pending Credential with a reason (Admin action).

    Raises:
        HTTPException(404): Credential not found.
        HTTPException(422): Credential is not pending.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        credential = await _load_credential_for_review(db, credential_id)
        if credential.verification_status != "pending":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only pending credentials can be rejected.",
            )
        credential.verification_status = "rejected"
        credential.rejection_reason = reason
        credential.reviewed_by = admin_id
        credential.verified_at = None
        owner_id = credential.user_id
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="credential_rejected",
            target_type="credential",
            target_id=credential.id,
            metadata={"owner_id": str(owner_id), "reason": reason},
        )
        await db.flush()
        await db.refresh(credential)
    _notify_credential_decision(user_id=owner_id, credential=credential, verified=False)
    return credential
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py -k "verify or reject" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/attestation/credential_service.py backend/tests/integration/test_credential_verification.py
git commit -m "feat(credentials): admin verify/reject with audit + owner notification"
```

---

## Task 5: Service — edit-reset rule on update_credential

**Files:**
- Modify: `backend/app/modules/attestation/credential_service.py`
- Test: `backend/tests/integration/test_credential_verification.py`

- [ ] **Step 1: Write the failing test**

Add:

```python
async def test_editing_material_field_resets_verification(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """Editing title on a verified credential resets it to unverified."""
    del migrated_database, credential_context
    owner_id = await create_user("reset-owner@auracles.space", ["contributor"])
    credential_id = await _seed_credential(
        owner_id,
        reference_number="PMP-1",
        verification_status="verified",
    )
    from app.modules.attestation.schemas import CredentialUpdateRequest

    async with async_session_factory() as session:
        user = await session.get(User, owner_id)
        result = await credential_service.update_credential(
            db=session,
            user=user,
            credential_id=credential_id,
            payload=CredentialUpdateRequest(title="PMP Renewed"),
        )
    assert result.verification_status == "unverified"
    assert result.verified_at is None
    assert result.reviewed_by is None


async def test_editing_non_material_field_keeps_verification(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """Editing expires_date does not reset a verified credential."""
    del migrated_database, credential_context
    owner_id = await create_user("keep-owner@auracles.space", ["contributor"])
    credential_id = await _seed_credential(
        owner_id, reference_number="PMP-1", verification_status="verified"
    )
    from app.modules.attestation.schemas import CredentialUpdateRequest

    async with async_session_factory() as session:
        user = await session.get(User, owner_id)
        result = await credential_service.update_credential(
            db=session,
            user=user,
            credential_id=credential_id,
            payload=CredentialUpdateRequest(expires_date="2030-01-01"),
        )
    assert result.verification_status == "verified"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py -k "reset or non_material" -v`
Expected: FAIL — material fields not handled; also `update_credential` must accept the new fields.

- [ ] **Step 3: Implement edit-reset + accept new fields in `update_credential`**

In `update_credential`, replace the field-assignment block with one that applies new metadata fields, detects material changes, and resets verification. Material fields: `title`, `issuer`, `issued_date`, `reference_number`. Insert after loading `credential` and before `await db.flush()`:

```python
        material_changed = False
        if payload.title is not None and payload.title != credential.title:
            credential.title = payload.title
            material_changed = True
        if payload.issuer is not None and payload.issuer != credential.issuer:
            credential.issuer = payload.issuer
            material_changed = True
        if (
            payload.issued_date is not None
            and payload.issued_date != credential.issued_date
        ):
            credential.issued_date = payload.issued_date
            material_changed = True
        if "expires_date" in payload.model_fields_set:
            credential.expires_date = payload.expires_date
        if payload.credential_type is not None:
            credential.credential_type = payload.credential_type
        if payload.verification_url is not None:
            credential.verification_url = payload.verification_url
        if (
            payload.reference_number is not None
            and payload.reference_number != credential.reference_number
        ):
            credential.reference_number = payload.reference_number
            material_changed = True
        if payload.issuer_type is not None:
            credential.issuer_type = payload.issuer_type
        if payload.evidence_file_keys is not None:
            await _consume_credential_evidence_sessions(
                db=db,
                credential_id=credential.id,
                user_id=user_id,
                file_keys=payload.evidence_file_keys,
                now=datetime.now(UTC),
            )
            credential.evidence_file_keys = payload.evidence_file_keys
        if material_changed and credential.verification_status in {
            "pending",
            "verified",
        }:
            credential.verification_status = "unverified"
            credential.submitted_at = None
            credential.verified_at = None
            credential.reviewed_by = None
            credential.rejection_reason = None
            await write_audit(
                db=db,
                actor_id=user_id,
                action="credential_verification_reset",
                target_type="credential",
                target_id=credential.id,
                metadata={"title": credential.title},
            )
```

(Delete the previous simpler assignment block this replaces.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py -k "reset or non_material" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/attestation/credential_service.py backend/tests/integration/test_credential_verification.py
git commit -m "feat(credentials): edit-reset verification on material field change"
```

---

## Task 6: Owner submit endpoint + response `expired` derivation

**Files:**
- Modify: `backend/app/modules/attestation/router.py`
- Test: `backend/tests/integration/test_credential_verification.py`

- [ ] **Step 1: Write the failing test**

Add:

```python
def _credential_response_with_expired(payload: dict) -> dict:
    return payload


async def test_submit_endpoint_owner_only(
    client: AsyncClient, migrated_database: None, credential_context: FakeRedis
) -> None:
    """Owner can submit; a non-owner gets 404; response carries verification_status."""
    del migrated_database, credential_context
    owner_id = await create_user("ep-owner@auracles.space", ["contributor"])
    outsider_id = await create_user("ep-outsider@auracles.space", ["contributor"])
    credential_id = str(await _seed_credential(owner_id, reference_number="PMP-1"))

    outsider = await client.post(
        f"/v1/credentials/{credential_id}/submit",
        headers=auth_headers(outsider_id, ["contributor"]),
    )
    owner = await client.post(
        f"/v1/credentials/{credential_id}/submit",
        headers=auth_headers(owner_id, ["contributor"]),
    )
    assert outsider.status_code == 404
    assert owner.status_code == 200
    assert owner.json()["verification_status"] == "pending"
    assert owner.json()["expired"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py -k submit_endpoint -v`
Expected: FAIL — route + `expired` missing.

- [ ] **Step 3: Add an `expired`-aware response builder and the submit route**

In `backend/app/modules/attestation/router.py`, add a helper after the type aliases:

```python
from datetime import date as _date

from app.modules.attestation.models import Credential as _CredentialModel


def _credential_response(credential: _CredentialModel) -> CredentialResponse:
    """Build a CredentialResponse with the derived ``expired`` flag."""
    expired = (
        credential.expires_date is not None
        and credential.expires_date < _date.today()
    )
    return CredentialResponse.model_validate(
        {
            **{
                column: getattr(credential, column)
                for column in (
                    "id",
                    "user_id",
                    "title",
                    "issuer",
                    "issued_date",
                    "expires_date",
                    "evidence_file_keys",
                    "credential_type",
                    "verification_url",
                    "reference_number",
                    "issuer_type",
                    "verification_status",
                    "submitted_at",
                    "verified_at",
                    "reviewed_by",
                    "rejection_reason",
                    "created_at",
                    "updated_at",
                )
            },
            "expired": expired,
        }
    )
```

Replace the four existing `CredentialResponse.model_validate(credential)` call sites in `create_credential`, `list_credentials`, and `update_credential` with `_credential_response(credential)`. Add the submit route after `update_credential`:

```python
@router.post(
    "/credentials/{credential_id}/submit",
    response_model=CredentialResponse,
)
async def submit_credential(
    credential_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> CredentialResponse:
    """Submit an owned Credential for manual Admin verification."""
    credential = await credential_service.submit_credential(
        db=db, user=user, credential_id=credential_id
    )
    return _credential_response(credential)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py -k submit_endpoint -v`
Expected: PASS.

Also re-run the existing credential suite to confirm no regression from the response-shape change:
Run: `cd backend && uv run pytest tests/integration/test_credentials.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/attestation/router.py backend/tests/integration/test_credential_verification.py
git commit -m "feat(credentials): owner submit endpoint + derived expired flag"
```

---

## Task 7: Admin review queue + verify/reject endpoints

**Files:**
- Modify: `backend/app/modules/admin/router.py`, `backend/app/modules/admin/schemas.py`
- Modify: `backend/app/modules/attestation/credential_service.py` (add `list_credentials_for_review`)
- Test: `backend/tests/integration/test_credential_verification.py`

- [ ] **Step 1: Write the failing test**

Add:

```python
async def test_admin_queue_and_decisions(
    client: AsyncClient, migrated_database: None, credential_context: FakeRedis
) -> None:
    """Admin lists pending queue and verifies; non-admin is forbidden."""
    del migrated_database, credential_context
    admin_id = await create_user("queue-admin@auracles.space", ["admin"])
    owner_id = await create_user("queue-owner@auracles.space", ["contributor"])
    credential_id = str(
        await _seed_credential(
            owner_id, reference_number="PMP-1", verification_status="pending"
        )
    )

    forbidden = await client.get(
        "/v1/admin/credentials",
        headers=auth_headers(owner_id, ["contributor"]),
    )
    queue = await client.get(
        "/v1/admin/credentials?status=pending",
        headers=auth_headers(admin_id, ["admin"]),
    )
    verified = await client.post(
        f"/v1/admin/credentials/{credential_id}/verify",
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert forbidden.status_code == 403
    assert queue.status_code == 200
    assert credential_id in [c["id"] for c in queue.json()["credentials"]]
    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "verified"


async def test_admin_reject_requires_reason(
    client: AsyncClient, migrated_database: None, credential_context: FakeRedis
) -> None:
    """Admin reject with empty reason is a 422; with reason it succeeds."""
    del migrated_database, credential_context
    admin_id = await create_user("rej-admin@auracles.space", ["admin"])
    owner_id = await create_user("rej-owner@auracles.space", ["contributor"])
    credential_id = str(
        await _seed_credential(
            owner_id, reference_number="PMP-1", verification_status="pending"
        )
    )

    empty = await client.post(
        f"/v1/admin/credentials/{credential_id}/reject",
        headers=auth_headers(admin_id, ["admin"]),
        json={"reason": ""},
    )
    ok = await client.post(
        f"/v1/admin/credentials/{credential_id}/reject",
        headers=auth_headers(admin_id, ["admin"]),
        json={"reason": "Issuer registry shows no match."},
    )
    assert empty.status_code == 422
    assert ok.status_code == 200
    assert ok.json()["verification_status"] == "rejected"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py -k "admin_queue or admin_reject" -v`
Expected: FAIL — admin endpoints + `list_credentials_for_review` missing.

- [ ] **Step 3: Add the review-queue service function**

In `credential_service.py`:

```python
async def list_credentials_for_review(
    db: AsyncSession, verification_status: str | None = "pending"
) -> list[Credential]:
    """Return credentials filtered by verification status for admin review."""
    stmt = select(Credential).order_by(Credential.submitted_at.desc().nullslast())
    if verification_status is not None:
        stmt = stmt.where(Credential.verification_status == verification_status)
    result = await db.execute(stmt)
    return list(result.scalars().all())
```

- [ ] **Step 4: Add admin schemas import + endpoints**

In `backend/app/modules/admin/schemas.py`, re-export or define the request body. Add:

```python
from pydantic import BaseModel, Field


class AdminCredentialRejectBody(BaseModel):
    """Admin request body for rejecting a pending Credential."""

    reason: str = Field(min_length=1, max_length=4000)
```

(If `admin/schemas.py` already imports `BaseModel`/`Field`, just add the class.)

In `backend/app/modules/admin/router.py`, add imports at the top with the other module imports:

```python
from typing import Annotated, Literal

from app.modules.attestation import credential_service
from app.modules.attestation.schemas import (
    AdminCredentialResponse,
    AdminCredentialsResponse,
)
from app.modules.admin.schemas import AdminCredentialRejectBody
```

Then append the three endpoints (after `review_kyc`):

```python
@router.get("/credentials", response_model=AdminCredentialsResponse)
async def list_credential_review_queue(
    admin: AdminUser,
    db: DatabaseSession,
    status_filter: Annotated[
        Literal["unverified", "pending", "verified", "rejected"] | None,
        Query(alias="status"),
    ] = "pending",
) -> AdminCredentialsResponse:
    """List credentials awaiting (or filtered by) verification status."""
    credentials = await credential_service.list_credentials_for_review(
        db=db, verification_status=status_filter
    )
    return AdminCredentialsResponse(
        credentials=[
            AdminCredentialResponse.model_validate(credential)
            for credential in credentials
        ]
    )


@router.post(
    "/credentials/{credential_id}/verify",
    response_model=AdminCredentialResponse,
)
async def verify_credential(
    credential_id: UUID,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminCredentialResponse:
    """Mark a pending Credential verified."""
    credential = await credential_service.verify_credential(
        db=db, admin_id=admin.id, credential_id=credential_id
    )
    return AdminCredentialResponse.model_validate(credential)


@router.post(
    "/credentials/{credential_id}/reject",
    response_model=AdminCredentialResponse,
)
async def reject_credential(
    credential_id: UUID,
    payload: AdminCredentialRejectBody,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminCredentialResponse:
    """Reject a pending Credential with a reason."""
    credential = await credential_service.reject_credential(
        db=db,
        admin_id=admin.id,
        credential_id=credential_id,
        reason=payload.reason,
    )
    return AdminCredentialResponse.model_validate(credential)
```

Ensure `Query` and `UUID` are imported in the admin router (add `from fastapi import ... Query` and `from uuid import UUID` if not already present — check the existing import block).

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_credential_verification.py -k "admin_queue or admin_reject" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/admin/router.py backend/app/modules/admin/schemas.py backend/app/modules/attestation/credential_service.py backend/tests/integration/test_credential_verification.py
git commit -m "feat(credentials): admin review queue + verify/reject endpoints"
```

---

## Task 8: Public exposure — verified credentials on contributor profile

**Files:**
- Modify: `backend/app/modules/explore/schemas.py`, `backend/app/modules/explore/service.py`
- Test: `backend/tests/integration/test_explore_contributor_credentials.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_explore_contributor_credentials.py`:

```python
"""Public contributor profile exposes verified credentials only, no PII."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import hash_password
from app.main import app
from app.modules.attestation.models import Credential
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework  # adjust if framework model path differs


class FakeRedis:
    """Redis double."""


@pytest.fixture
def migrated_database() -> Iterator[None]:
    sync_engine = create_engine(app.state.settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def context() -> AsyncIterator[FakeRedis]:
    fake = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(Credential))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
    app.dependency_overrides[get_redis] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


async def test_profile_shows_verified_only_no_sensitive_fields(
    client: AsyncClient, migrated_database: None, context: FakeRedis
) -> None:
    """Profile lists a verified credential and never a pending one or its evidence."""
    del migrated_database, context
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email="pub-contrib@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Pub Contrib",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role="contributor", approved_at=datetime.now(UTC))
            )
            session.add(
                Framework(
                    contributor_id=user.id,
                    title="Pub FW",
                    status="published",
                    published_at=datetime.now(UTC),
                )
            )
            session.add(
                Credential(
                    user_id=user.id,
                    title="PMP",
                    issuer="PMI",
                    issued_date=date(2024, 1, 1),
                    credential_type="PMP",
                    reference_number="SECRET-REF",
                    verification_url="https://secret",
                    evidence_file_keys=["s3-secret-key"],
                    verification_status="verified",
                )
            )
            session.add(
                Credential(
                    user_id=user.id,
                    title="Pending Cert",
                    issuer="X",
                    issued_date=date(2024, 1, 1),
                    verification_status="pending",
                )
            )
            user_id = user.id

    response = await client.get(f"/v1/explore/contributors/{user_id}")
    assert response.status_code == 200
    creds = response.json()["verified_credentials"]
    titles = [c["title"] for c in creds]
    assert titles == ["PMP"]
    serialized = response.text
    assert "SECRET-REF" not in serialized
    assert "s3-secret-key" not in serialized
    assert "https://secret" not in serialized
```

(If the `Framework` import path or required columns differ, mirror the construction used in `backend/tests/integration/test_explore_*` for a published framework — those tests already build a publishable framework for this exact endpoint.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_explore_contributor_credentials.py -v`
Expected: FAIL — `verified_credentials` not in the response.

- [ ] **Step 3: Add the field to the profile schema**

In `backend/app/modules/explore/schemas.py`, import the public schema at top:

```python
from app.modules.attestation.schemas import PublicCredentialResponse
```

Add to `ExploreContributorProfile` (after `published_frameworks`):

```python
    verified_credentials: list[PublicCredentialResponse] = []
```

- [ ] **Step 4: Populate it in the service**

In `backend/app/modules/explore/service.py`, add the import:

```python
from app.modules.attestation.models import Credential
from app.modules.attestation.schemas import PublicCredentialResponse
```

Inside `get_contributor_profile`, before the `return ExploreContributorProfile(...)`, add:

```python
    from datetime import date as _date

    credential_rows = await db.execute(
        select(Credential)
        .where(
            Credential.user_id == contributor_id,
            Credential.verification_status == "verified",
        )
        .order_by(Credential.issued_date.desc())
    )
    verified_credentials = [
        PublicCredentialResponse(
            title=credential.title,
            issuer=credential.issuer,
            credential_type=credential.credential_type,
            issued_date=credential.issued_date,
            expires_date=credential.expires_date,
            expired=(
                credential.expires_date is not None
                and credential.expires_date < _date.today()
            ),
        )
        for credential in credential_rows.scalars().all()
    ]
```

Then pass `verified_credentials=verified_credentials` into the `ExploreContributorProfile(...)` constructor.

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_explore_contributor_credentials.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/explore/schemas.py backend/app/modules/explore/service.py backend/tests/integration/test_explore_contributor_credentials.py
git commit -m "feat(credentials): verified credentials on public contributor profile"
```

---

## Task 9: OpenAPI + frontend client sync + full verification

**Files:**
- Modify: `contracts/openapi.yaml`, `frontend/src/lib/generated/types.gen.ts`

- [ ] **Step 1: Hand-edit `contracts/openapi.yaml`**

This repo's `contracts/openapi.yaml` is **hand-maintained** (CI only validates it; there is no export script — the prior `avatar_url` change was hand-added). Add by hand, matching the existing 3.1.0 style:
- `paths`: `POST /v1/credentials/{credential_id}/submit` (tag `Attestation`, 200 → `CredentialResponse`, security bearer); `GET /v1/admin/credentials` (tag `Admin`, query `status`, 200 → `AdminCredentialsResponse`); `POST /v1/admin/credentials/{credential_id}/verify` and `.../reject` (tag `Admin`, 200 → `AdminCredentialResponse`; reject body `AdminCredentialRejectBody`).
- `components.schemas`: extend `CredentialResponse` with the new fields (`credential_type`, `verification_url`, `reference_number`, `issuer_type`, `verification_status`, `submitted_at`, `verified_at`, `reviewed_by`, `rejection_reason`, `expired`); extend `CredentialCreateRequest`/`CredentialUpdateRequest` with the four metadata fields; add `AdminCredentialResponse`, `AdminCredentialsResponse`, `AdminCredentialRejectBody`, `PublicCredentialResponse`; add `verified_credentials` to `ExploreContributorProfile`.

Tip to avoid hand-drift: temporarily dump the live schema and diff — `cd backend && uv run python -c "import json,yaml; from app.main import app; print(yaml.safe_dump(app.openapi()))" > /tmp/live.yaml` — then port the credential-related deltas into `contracts/openapi.yaml`. Do **not** wholesale-replace the file (it is curated).

- [ ] **Step 2: Regenerate the frontend client**

Run: `cd frontend && pnpm run generate:api` (reads `../contracts/openapi.yaml` via `openapi-ts.config.ts`).
Expected: `frontend/src/lib/generated/types.gen.ts` + `sdk.gen.ts` updated with the new schemas/paths.

- [ ] **Step 3: Validate the contract**

Run: `cd backend && uv run openapi-spec-validator ../contracts/openapi.yaml`
Expected: no errors.

- [ ] **Step 4: Run the full backend suite + coverage + lint + types**

Run:
```bash
cd backend && uv run ruff check . && uv run mypy app && \
uv run pytest --cov=app.modules --cov=app.workers --cov-fail-under=80
```
Expected: all green, coverage ≥ 80%.

Run migration round-trip once more:
```bash
cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add contracts/openapi.yaml frontend/src/lib/generated/
git commit -m "chore(credentials): sync OpenAPI contract + frontend client types"
```

---

## Self-review notes (coverage against spec)

- Spec §Data model → Task 1 (enums, columns, index, FK, round-trip).
- Spec §Lifecycle `submit` + evidence gate → Task 3; `verify`/`reject` + notify + audit → Task 4; edit-reset → Task 5.
- Spec §API user submit → Task 6; admin queue/verify/reject → Task 7.
- Spec §API public display (verified-only, no sensitive fields) → Task 8 (explicit leak assertions).
- Spec §Security: admin RBAC (Task 7 `forbidden` 403), owner-only submit (Task 6 404), public payload omits evidence/url/reference (Task 8), audit on every transition (Tasks 3–5 `write_audit`), notify on verify/reject (Task 4).
- Spec §Testing: state-machine unit/integration (Tasks 3–5), admin RBAC (Task 7), public leak (Task 8), migration up/down (Tasks 1, 9), coverage ≥ 80% (Task 9).
- Out-of-scope confirmed absent: no issuer-API, no adapter, no operator business verification, no reputation, no `revoked`, no 2FA on credential admin endpoints (verify/reject take no `totp_code` — matches spec "not a money op").

## Open confirmations for the implementer

- **`Framework` construction in Task 8 test:** mirror whatever the existing `test_explore_*` integration tests use to seed a published framework (required columns may exceed `title/status/published_at`). Reuse their helper rather than reconstructing it.
- **`tests/unit/modules/` DB access:** confirm whether neighbors in that dir hit the live DB. If they are pure-unit (no DB), keep the DB-backed service assertions in the integration file (as Task 3+ already do) and leave only the pure schema tests in `tests/unit/modules/test_credential_verification_service.py`.
