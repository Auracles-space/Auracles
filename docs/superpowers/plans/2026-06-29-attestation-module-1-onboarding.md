# Attestation Module 1 — Attestor Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the gated Attestor onboarding flow (application → KYC → credential cross-check → trial → CoI/taxonomy/payout → ACTIVE + directory) advancing through verification levels 1–4.

**Architecture:** Extend the existing `attestation` module. `AttestorApplication` drives a server-enforced state machine; each gate is one transition function (lock → validate state → advance → audit). The `AttestorProfile` + `attestor` role are created **only** at the ACTIVE transition, replacing today's approve-time creation. A public directory reads active profiles. Trial is stubbed (admin manual pass/fail) until Module 4 provides the rubric.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, PostgreSQL 16, pytest + httpx `AsyncClient`, loguru.

## Global Constraints

- Python 3.13; backend lives in `backend/`, run tooling with `uv run`.
- TDD: failing test first, minimal code, then green. One behavior per cycle.
- Every DB write touching multiple rows uses a transaction (`async with db.begin()`); follow the `application_service.py` `if db.in_transaction(): await db.rollback()` preamble.
- RBAC at the FastAPI dependency layer only (`require_role`, `require_approved_attestor`); never in services.
- Admin sensitive actions require verified TOTP via `auth_service.verify_totp_for_sensitive_action(db, redis, user, code)`.
- Pydantic schema on every request body; response models explicit with `model_config = ConfigDict(from_attributes=True)`; never return ORM objects raw.
- Errors: business-rule → `HTTPException(422)`; auth → 401/403; not-found → 404; conflict → 409. Never bare `Exception`.
- Logging: `loguru`, `logger.bind(module="attestation", action=..., ...)`. Never log PII (CoI entities, tax/credential references, payout details) or secrets.
- Audit every state transition + admin gate via `app.core.audit.write_audit(db=, actor_id=, action=, target_type=, target_id=, metadata=)`.
- Migrations: one file under `migrations/versions/`, filename `YYYY_MM_DD_NNNN_description.py`; current head is `2026_06_28_0040`. `alembic upgrade head` and `downgrade -1` must both succeed. Google-style docstrings on every module/class/public function.
- Money/PII never in list endpoints; directory exposes only verified credentials + coarse level.
- OpenAPI-first: update `contracts/openapi.yaml` then regenerate the frontend client, after backend endpoints land.
- **Org-redefine flag:** verification levels, credential cross-check, personal CoI, directory credential display are individual-specific; keep them isolated.

**Test commands:** unit `uv run pytest tests/unit/modules/test_attestor_onboarding_service.py -v`; integration `uv run pytest tests/integration/test_attestor_onboarding.py -v`; whole-repo gate before claiming done: `uv run ruff check .` and `uv run mypy app`.

**Test infrastructure (reuse, do not reinvent):** `tests/integration/test_attestor_applications.py` defines `FakeRedis`, the `migrated_database` fixture, the `attestor_application_context` fixture (resets tables + installs FakeRedis), and `async def create_user(email, roles) -> UUID`. New integration tests import/extend these. Auth header: `f"Bearer {create_access_token(str(user_id))}"`. TOTP: `pyotp.TOTP(secret).now()` with `encrypt_totp_secret`.

---

### Task 1: Schema migration — onboarding columns, enums, trials table

**Files:**
- Create: `backend/migrations/versions/2026_06_29_0041_attestor_onboarding.py`
- Test: `backend/tests/unit/test_attestor_onboarding_migration.py`

**Interfaces:**
- Produces: DB columns/tables consumed by all later tasks — `attestor_applications` new columns/enum values; `attestor_profiles` new columns; `credentials` cross-check columns; new `attestor_trials` table; new enums `attestor_trial_status_enum`, `attestor_credential_body_enum`, `tax_document_type_enum`.

**Notes:** Postgres `ALTER TYPE ... ADD VALUE` cannot run inside the alembic transaction — wrap enum-value additions in `with op.get_context().autocommit_block():`. New columns are nullable or have server defaults so the migration is backwards-compatible. Data mapping: set `status='submitted'` where `status='pending'`, `status='active'` where `status='approved'` (legacy approved attestors stay live). Copy legacy `attestor_applications.specializations` into new `sectors` (best-effort; also set `needs_retag=true`).

- [ ] **Step 1: Write the failing migration round-trip test**

```python
"""Migration round-trip test for the Attestor onboarding schema."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.main import app


def test_onboarding_migration_upgrades_and_downgrades() -> None:
    """attestor onboarding columns + trials table exist after upgrade; clean downgrade."""
    cfg = Config("alembic.ini")
    engine = create_engine(app.state.settings.sync_database_url, pool_pre_ping=True)
    try:
        command.upgrade(cfg, "head")
        insp = inspect(engine)
        app_cols = {c["name"] for c in insp.get_columns("attestor_applications")}
        assert {"legal_name", "linkedin_url", "professional_body_numbers",
                "cv_file_key", "coi_declarations", "coi_signed_at", "coi_expires_at",
                "sectors", "framework_categories", "needs_retag",
                "kyc_verified_at", "kyc_name_match"} <= app_cols
        prof_cols = {c["name"] for c in insp.get_columns("attestor_profiles")}
        assert {"verification_level", "sectors", "framework_categories",
                "coi_declarations", "coi_signed_at", "coi_expires_at"} <= prof_cols
        cred_cols = {c["name"] for c in insp.get_columns("credentials")}
        assert {"issuing_body", "good_standing", "registry_checked_at",
                "registry_checked_by", "registry_reference"} <= cred_cols
        assert "attestor_trials" in insp.get_table_names()
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()
```

- [ ] **Step 2: Run it, verify it fails**

Run: `uv run pytest tests/unit/test_attestor_onboarding_migration.py -v`
Expected: FAIL (columns/table missing).

- [ ] **Step 3: Write the migration**

```python
"""Add Attestor onboarding gates: levels, CoI, taxonomy, credential cross-check, trials.

Supports Module 1 (Attestor Onboarding). Extends attestor_applications into a
gated state machine, adds verification levels + taxonomy + CoI to profiles,
adds manual registry cross-check fields to credentials, and a stubbed
attestor_trials table for calibration.

Revision ID: 2026_06_29_0041
Revises: 2026_06_28_0040
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_29_0041"
down_revision: str | Sequence[str] | None = "2026_06_28_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_APP_STATUSES = (
    "submitted", "identity_verified", "professional_verified",
    "expert_verified", "active", "held",
)


def upgrade() -> None:
    """Add onboarding columns, new enums, and the attestor_trials table."""
    # 1. Extend the application status enum (ADD VALUE needs autocommit).
    with op.get_context().autocommit_block():
        for value in _NEW_APP_STATUSES:
            op.execute(
                f"ALTER TYPE attestor_application_status_enum ADD VALUE IF NOT EXISTS '{value}'"
            )

    # 2. New enums.
    trial_status = postgresql.ENUM(
        "assigned", "passed", "failed", name="attestor_trial_status_enum"
    )
    body = postgresql.ENUM(
        "cfa_institute", "aicpa", "isaca", "rics", "sra", "state_bar",
        "fca", "acams", "other", name="attestor_credential_body_enum",
    )
    tax_type = postgresql.ENUM(
        "w9", "w8ben", "other", name="tax_document_type_enum"
    )
    bind = op.get_bind()
    trial_status.create(bind, checkfirst=True)
    body.create(bind, checkfirst=True)
    tax_type.create(bind, checkfirst=True)

    # 3. attestor_applications new columns.
    op.add_column("attestor_applications", sa.Column("legal_name", sa.Text(), nullable=True))
    op.add_column("attestor_applications", sa.Column("linkedin_url", sa.Text(), nullable=True))
    op.add_column("attestor_applications", sa.Column(
        "professional_body_numbers", postgresql.JSONB(),
        nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("attestor_applications", sa.Column("cv_file_key", sa.Text(), nullable=True))
    op.add_column("attestor_applications", sa.Column(
        "coi_declarations", postgresql.JSONB(),
        nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("attestor_applications", sa.Column("coi_signed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("attestor_applications", sa.Column("coi_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("attestor_applications", sa.Column(
        "sectors", postgresql.ARRAY(sa.Text()), nullable=False,
        server_default=sa.text("'{}'::text[]")))
    op.add_column("attestor_applications", sa.Column(
        "framework_categories", postgresql.ARRAY(sa.Text()), nullable=False,
        server_default=sa.text("'{}'::text[]")))
    op.add_column("attestor_applications", sa.Column(
        "needs_retag", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("attestor_applications", sa.Column("kyc_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("attestor_applications", sa.Column("kyc_name_match", sa.Boolean(), nullable=True))
    op.add_column("attestor_applications", sa.Column(
        "tax_document_type", sa.Enum(name="tax_document_type_enum", create_type=False), nullable=True))
    op.add_column("attestor_applications", sa.Column("tax_document_key", sa.Text(), nullable=True))
    op.add_column("attestor_applications", sa.Column("payout_account_id", postgresql.UUID(as_uuid=True),
        sa.ForeignKey("payout_accounts.id", ondelete="SET NULL"), nullable=True))

    # 4. Data migration: map legacy statuses + seed sectors from specializations.
    op.execute("UPDATE attestor_applications SET status='submitted' WHERE status='pending'")
    op.execute("UPDATE attestor_applications SET status='active' WHERE status='approved'")
    op.execute("UPDATE attestor_applications SET sectors=specializations, needs_retag=true "
               "WHERE array_length(specializations, 1) IS NOT NULL")

    # 5. attestor_profiles new columns.
    op.add_column("attestor_profiles", sa.Column(
        "verification_level", sa.Integer(), nullable=False, server_default=sa.text("1")))
    op.add_column("attestor_profiles", sa.Column(
        "sectors", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")))
    op.add_column("attestor_profiles", sa.Column(
        "framework_categories", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")))
    op.add_column("attestor_profiles", sa.Column(
        "coi_declarations", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("attestor_profiles", sa.Column("coi_signed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("attestor_profiles", sa.Column("coi_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE attestor_profiles SET sectors=specializations "
               "WHERE array_length(specializations, 1) IS NOT NULL")
    op.create_index("idx_attestor_profiles_sectors_gin", "attestor_profiles", ["sectors"],
                    postgresql_using="gin")
    op.create_index("idx_attestor_profiles_categories_gin", "attestor_profiles",
                    ["framework_categories"], postgresql_using="gin")

    # 6. credentials cross-check columns.
    op.add_column("credentials", sa.Column(
        "issuing_body", sa.Enum(name="attestor_credential_body_enum", create_type=False), nullable=True))
    op.add_column("credentials", sa.Column("good_standing", sa.Boolean(), nullable=True))
    op.add_column("credentials", sa.Column("registry_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("credentials", sa.Column("registry_checked_by", postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("credentials", sa.Column("registry_reference", sa.Text(), nullable=True))

    # 7. attestor_trials table.
    op.create_table(
        "attestor_trials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("application_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("attestor_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seeded_framework_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("frameworks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Enum(name="attestor_trial_status_enum", create_type=False),
                  nullable=False, server_default="assigned"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("attempt >= 1 AND attempt <= 2", name="ck_attestor_trials_attempt_range"),
    )
    op.create_index("idx_attestor_trials_application", "attestor_trials", ["application_id"])


def downgrade() -> None:
    """Drop onboarding columns, indexes, trials table, and new enums.

    Enum *values* added to attestor_application_status_enum are not removed
    (Postgres cannot drop enum values); this is acceptable and non-breaking.
    """
    op.drop_index("idx_attestor_trials_application", table_name="attestor_trials")
    op.drop_table("attestor_trials")
    for col in ("registry_reference", "registry_checked_by", "registry_checked_at",
                "good_standing", "issuing_body"):
        op.drop_column("credentials", col)
    op.drop_index("idx_attestor_profiles_categories_gin", table_name="attestor_profiles")
    op.drop_index("idx_attestor_profiles_sectors_gin", table_name="attestor_profiles")
    for col in ("coi_expires_at", "coi_signed_at", "coi_declarations",
                "framework_categories", "sectors", "verification_level"):
        op.drop_column("attestor_profiles", col)
    for col in ("payout_account_id", "tax_document_key", "tax_document_type",
                "kyc_name_match", "kyc_verified_at", "needs_retag",
                "framework_categories", "sectors", "coi_expires_at", "coi_signed_at",
                "coi_declarations", "cv_file_key", "professional_body_numbers",
                "linkedin_url", "legal_name"):
        op.drop_column("attestor_applications", col)
    bind = op.get_bind()
    for name in ("attestor_trial_status_enum", "attestor_credential_body_enum",
                 "tax_document_type_enum"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `uv run pytest tests/unit/test_attestor_onboarding_migration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/2026_06_29_0041_attestor_onboarding.py backend/tests/unit/test_attestor_onboarding_migration.py
git commit -m "feat(attestation): onboarding schema migration"
```

---

### Task 2: SQLAlchemy models for onboarding

**Files:**
- Modify: `backend/app/modules/attestation/models.py`
- Test: `backend/tests/unit/modules/test_attestor_onboarding_models.py`

**Interfaces:**
- Consumes: tables from Task 1.
- Produces: `AttestorTrial` ORM class; new mapped columns on `AttestorApplication`, `AttestorProfile`, `Credential`; module enums `ATTESTOR_TRIAL_STATUS_ENUM`, `ATTESTOR_CREDENTIAL_BODY_ENUM`, `TAX_DOCUMENT_TYPE_ENUM`. New application status values usable on `AttestorApplication.status`.

- [ ] **Step 1: Write the failing test**

```python
"""Model-level tests for Attestor onboarding columns and the trials table."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.attestation.models import AttestorApplication, AttestorTrial
from app.modules.auth.models import User
from app.core.security import hash_password


@pytest.mark.usefixtures("migrated_database")
async def test_application_persists_onboarding_fields_and_trial() -> None:
    """An application stores taxonomy + CoI fields and links a trial row."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(email="t-models@example.com",
                        password_hash=hash_password("CorrectHorse9"),
                        display_name="t", email_verified=True)
            session.add(user)
            await session.flush()
            appn = AttestorApplication(
                user_id=user.id, status="submitted",
                legal_name="Jane Q Attestor",
                sectors=["PE"], framework_categories=["Compliance"],
                jurisdictions=["US"], credentials_summary="x" * 12,
                sample_work={}, professional_references="ref",
                coi_declarations=[{"entity": "Acme", "entity_type": "firm",
                                   "relationship": "employment", "within_24mo": True}],
            )
            session.add(appn)
            await session.flush()
            session.add(AttestorTrial(application_id=appn.id, status="assigned", attempt=1))
        loaded = await session.scalar(
            select(AttestorApplication).where(AttestorApplication.id == appn.id))
        assert loaded.sectors == ["PE"]
        assert loaded.coi_declarations[0]["entity"] == "Acme"
```

(Use the `migrated_database` fixture by adding it to this test module's imports/conftest — copy the fixture from `tests/integration/test_attestor_applications.py` into a shared `tests/unit/modules/conftest.py` if not already importable.)

- [ ] **Step 2: Run, verify fail**

Run: `uv run pytest tests/unit/modules/test_attestor_onboarding_models.py -v`
Expected: FAIL (`AttestorTrial` import error / unknown column).

- [ ] **Step 3: Add the enums, columns, and `AttestorTrial`**

In `models.py`, after the existing enum definitions add:

```python
ATTESTOR_TRIAL_STATUS_ENUM = ENUM(
    "assigned", "passed", "failed",
    name="attestor_trial_status_enum", create_type=False,
)
ATTESTOR_CREDENTIAL_BODY_ENUM = ENUM(
    "cfa_institute", "aicpa", "isaca", "rics", "sra", "state_bar",
    "fca", "acams", "other",
    name="attestor_credential_body_enum", create_type=False,
)
TAX_DOCUMENT_TYPE_ENUM = ENUM(
    "w9", "w8ben", "other", name="tax_document_type_enum", create_type=False,
)
```

Add to `AttestorApplication` (matching column names/types from Task 1): `legal_name: Mapped[str | None]`, `linkedin_url: Mapped[str | None]`, `professional_body_numbers: Mapped[dict[str, Any]]` (JSONB, default `{}`), `cv_file_key: Mapped[str | None]`, `coi_declarations: Mapped[list[dict[str, Any]]]` (JSONB), `coi_signed_at`/`coi_expires_at: Mapped[datetime | None]`, `sectors`/`framework_categories: Mapped[list[str]]` (ARRAY(Text)), `needs_retag: Mapped[bool]`, `kyc_verified_at: Mapped[datetime | None]`, `kyc_name_match: Mapped[bool | None]`, `tax_document_type: Mapped[str | None]` (use `TAX_DOCUMENT_TYPE_ENUM`), `tax_document_key: Mapped[str | None]`, `payout_account_id: Mapped[UUID | None]` (FK payout_accounts).

Add to `AttestorProfile`: `verification_level: Mapped[int]`, `sectors`/`framework_categories: Mapped[list[str]]`, `coi_declarations: Mapped[list[dict[str, Any]]]`, `coi_signed_at`/`coi_expires_at: Mapped[datetime | None]`.

Add to `Credential`: `issuing_body: Mapped[str | None]` (`ATTESTOR_CREDENTIAL_BODY_ENUM`), `good_standing: Mapped[bool | None]`, `registry_checked_at: Mapped[datetime | None]`, `registry_checked_by: Mapped[UUID | None]` (FK users), `registry_reference: Mapped[str | None]`.

New class:

```python
class AttestorTrial(CreatedAtMixin, Base):
    """Stubbed calibration trial for an Attestor application (manual pass/fail).

    Rubric-scored evaluation arrives with Module 4; for now an admin decides
    pass/fail. A second failure holds the application.
    """

    __tablename__ = "attestor_trials"
    __table_args__ = (
        CheckConstraint("attempt >= 1 AND attempt <= 2", name="ck_attestor_trials_attempt_range"),
        Index("idx_attestor_trials_application", "application_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True,
                                     server_default=text("gen_random_uuid()"))
    application_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestor_applications.id", ondelete="CASCADE"), nullable=False)
    seeded_framework_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("frameworks.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(ATTESTOR_TRIAL_STATUS_ENUM, nullable=False,
                                        server_default="assigned")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    decided_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/unit/modules/test_attestor_onboarding_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/attestation/models.py backend/tests/unit/modules/
git commit -m "feat(attestation): onboarding ORM models"
```

---

### Task 3: Controlled taxonomy vocabulary

**Files:**
- Create: `backend/app/modules/attestation/taxonomy.py`
- Test: `backend/tests/unit/modules/test_attestor_taxonomy.py`

**Interfaces:**
- Produces: `SECTORS: frozenset[str]`, `FRAMEWORK_CATEGORIES: frozenset[str]`, `validate_sectors(values: list[str]) -> list[str]`, `validate_categories(values: list[str]) -> list[str]` (trim, de-dupe, reject unknown via `ValueError`). Consumed by Task 4 schemas.

- [ ] **Step 1: Failing test**

```python
"""Tests for the controlled Attestor sector/category taxonomy."""

import pytest
from app.modules.attestation.taxonomy import (
    FRAMEWORK_CATEGORIES, SECTORS, validate_categories, validate_sectors,
)


def test_known_values_pass_and_dedupe() -> None:
    assert validate_sectors(["PE", "PE", "VC"]) == ["PE", "VC"]
    assert "Compliance" in FRAMEWORK_CATEGORIES


def test_unknown_value_rejected() -> None:
    with pytest.raises(ValueError):
        validate_sectors(["Crypto Hedge Fund"])
    with pytest.raises(ValueError):
        validate_categories(["Astrology"])
```

- [ ] **Step 2: Run, verify fail** — `uv run pytest tests/unit/modules/test_attestor_taxonomy.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement**

```python
"""Controlled Attestor specialisation taxonomy (Module 1.5).

Sector × Framework-Category vocabulary that drives AMM scoring (Module 3).
Replaces the prior free-text specializations.
"""

from __future__ import annotations

SECTORS: frozenset[str] = frozenset({"PE", "VC", "Infrastructure", "Real Estate"})
FRAMEWORK_CATEGORIES: frozenset[str] = frozenset({
    "Compliance", "Governance", "Risk", "Operations", "Legal",
    "Finance", "HR", "Technology", "Investment Management",
})


def _validate(values: list[str], allowed: frozenset[str], label: str) -> list[str]:
    """Trim, de-duplicate (first-seen), and reject values outside ``allowed``."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip()
        if item not in allowed:
            raise ValueError(f"{item!r} is not a valid {label}.")
        if item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    if not cleaned:
        raise ValueError(f"at least one {label} is required.")
    return cleaned


def validate_sectors(values: list[str]) -> list[str]:
    """Validate sector tags against the controlled set."""
    return _validate(values, SECTORS, "sector")


def validate_categories(values: list[str]) -> list[str]:
    """Validate framework-category tags against the controlled set."""
    return _validate(values, FRAMEWORK_CATEGORIES, "framework category")
```

- [ ] **Step 4: Run, verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat(attestation): controlled onboarding taxonomy"`

---

### Task 4: Application submission with onboarding fields

**Files:**
- Modify: `backend/app/modules/attestation/schemas.py`, `backend/app/modules/attestation/application_service.py`
- Test: `backend/tests/integration/test_attestor_onboarding.py` (new file)

**Interfaces:**
- Consumes: Task 2 models, Task 3 validators.
- Produces: `AttestorApplicationCreateRequest`/`UpdateRequest` carry `legal_name`, `linkedin_url`, `professional_body_numbers`, `sectors`, `framework_categories` (replacing `specializations`); `submit_application` sets `status="submitted"` and persists them. `AttestorApplicationResponse` adds `status`, `verification`-relevant fields, `sectors`, `framework_categories`, `needs_retag`.

- [ ] **Step 1: Failing integration test** (create the new test file; reuse fixtures from `test_attestor_applications.py` — import `FakeRedis`, `migrated_database`, `attestor_application_context`, `create_user`)

```python
"""Integration tests for the gated Attestor onboarding flow (Module 1)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from tests.integration.test_attestor_applications import (  # reuse shared helpers
    attestor_application_context, create_user, migrated_database,
)


@pytest.mark.usefixtures("migrated_database")
async def test_submit_application_starts_submitted_with_taxonomy(
    client: AsyncClient, attestor_application_context,
) -> None:
    """A submitted application is in 'submitted' state with controlled tags."""
    user_id = await create_user("appl@example.com", roles=["contributor"])
    resp = await client.post(
        "/v1/attestor/applications",
        headers={"Authorization": f"Bearer {create_access_token(str(user_id))}"},
        json={
            "legal_name": "Jane Q Attestor",
            "linkedin_url": "https://linkedin.com/in/jane",
            "professional_body_numbers": {"cfa_institute": "12345"},
            "sectors": ["PE"],
            "framework_categories": ["Compliance"],
            "jurisdictions": ["US"],
            "credentials_summary": "Twenty years compliance.",
            "sample_work": {},
            "professional_references": "ref",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "submitted"
    assert body["sectors"] == ["PE"]
    assert body["framework_categories"] == ["Compliance"]


@pytest.mark.usefixtures("migrated_database")
async def test_submit_rejects_unknown_sector(
    client: AsyncClient, attestor_application_context,
) -> None:
    """Unknown taxonomy values are rejected with 422."""
    user_id = await create_user("appl2@example.com", roles=["contributor"])
    resp = await client.post(
        "/v1/attestor/applications",
        headers={"Authorization": f"Bearer {create_access_token(str(user_id))}"},
        json={"legal_name": "X", "sectors": ["Crypto"],
              "framework_categories": ["Compliance"], "jurisdictions": ["US"],
              "credentials_summary": "x" * 12, "sample_work": {},
              "professional_references": "r"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run, verify fail** — `uv run pytest tests/integration/test_attestor_onboarding.py -v` → FAIL.

- [ ] **Step 3: Update schemas** — in `schemas.py` replace the `_AttestorApplicationFields` `specializations` field with `sectors` + `framework_categories` validated via the taxonomy, add `legal_name`, `linkedin_url`, `professional_body_numbers`:

```python
from app.modules.attestation.taxonomy import validate_categories, validate_sectors

class _AttestorApplicationFields(BaseModel):
    """Shared, sanitized fields for submitting and editing applications."""

    legal_name: str = Field(min_length=2, max_length=200)
    linkedin_url: str | None = Field(default=None, max_length=2048)
    professional_body_numbers: dict[str, str] = Field(default_factory=dict)
    sectors: list[str] = Field(min_length=1, max_length=4)
    framework_categories: list[str] = Field(min_length=1, max_length=9)
    jurisdictions: list[str] = Field(min_length=1, max_length=25)
    credentials_summary: str = Field(min_length=10, max_length=5000)
    sample_work: dict[str, Any] = Field(default_factory=dict)
    professional_references: str = Field(min_length=3, max_length=5000)

    @field_validator("sectors")
    @classmethod
    def _clean_sectors(cls, value: list[str]) -> list[str]:
        """Validate sectors against the controlled taxonomy."""
        return validate_sectors(value)

    @field_validator("framework_categories")
    @classmethod
    def _clean_categories(cls, value: list[str]) -> list[str]:
        """Validate framework categories against the controlled taxonomy."""
        return validate_categories(value)

    @field_validator("jurisdictions")
    @classmethod
    def _clean_jurisdictions(cls, value: list[str]) -> list[str]:
        """Trim/validate jurisdiction labels."""
        return _normalise_labels(value)

    @field_validator("legal_name", "credentials_summary", "professional_references")
    @classmethod
    def _clean_prose(cls, value: str) -> str:
        """Reject markup/control characters in prose fields."""
        return _ensure_safe_prose(value)
```

Update `AttestorApplicationResponse` to add `sectors: list[str]`, `framework_categories: list[str]`, `legal_name: str | None`, `needs_retag: bool` and drop `specializations`.

- [ ] **Step 4: Update `submit_application` + `update_application`** in `application_service.py` to persist the new fields and set `status="submitted"`:

```python
application = AttestorApplication(
    user_id=user_id,
    status="submitted",
    legal_name=payload.legal_name,
    linkedin_url=payload.linkedin_url,
    professional_body_numbers=payload.professional_body_numbers,
    sectors=payload.sectors,
    framework_categories=payload.framework_categories,
    jurisdictions=payload.jurisdictions,
    credentials_summary=payload.credentials_summary,
    sample_work=payload.sample_work,
    professional_references=payload.professional_references,
)
```

Change the existing-pending guard and `update_application` state check from `status == "pending"` to `status == "submitted"`. In `update_application` set the same new fields.

- [ ] **Step 5: Run tests, verify pass.** Run the two new tests + existing `tests/integration/test_attestor_applications.py` (update any now-broken assertions that referenced `specializations`/`pending` to `sectors`/`submitted`).

- [ ] **Step 6: Commit** — `git commit -m "feat(attestation): onboarding application fields + taxonomy"`

---

### Task 5: KYC verify gate → identity_verified (Level 1)

**Files:**
- Modify: `backend/app/modules/attestation/application_service.py`, `schemas.py`, `router.py`
- Test: `backend/tests/integration/test_attestor_onboarding.py`

**Interfaces:**
- Consumes: `auth_service.verify_totp_for_sensitive_action`, `User.kyc_status`.
- Produces: `verify_kyc(db, redis, admin, application_id, payload) -> AttestorApplication`; endpoint `POST /v1/admin/attestor/applications/{id}/verify-kyc`; request schema `AttestorKycVerifyRequest{name_match: bool, totp_code: str}`. Transition `submitted → identity_verified`, sets `kyc_verified_at`, `kyc_name_match`. Requires the applicant's `User.kyc_status == "verified"` and `name_match=True` else `422`.

- [ ] **Step 1: Failing test**

```python
@pytest.mark.usefixtures("migrated_database")
async def test_verify_kyc_advances_to_identity_verified(
    client: AsyncClient, attestor_application_context,
) -> None:
    """Admin KYC verify moves a submitted application to identity_verified."""
    # Helper builds: applicant with kyc_status=verified + submitted application,
    # plus a TOTP-enabled admin. See _seed_submitted_application + _admin_totp below.
    app_id, admin_headers, totp = await _seed_submitted_application(verified_kyc=True)
    resp = await client.post(
        f"/v1/admin/attestor/applications/{app_id}/verify-kyc",
        headers=admin_headers,
        json={"name_match": True, "totp_code": totp.now()},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "identity_verified"
```

(Add `_seed_submitted_application(...)` and `_admin_totp()` helpers at the top of the test module: create applicant via `create_user`, set `user.kyc_status="verified"`, insert an `AttestorApplication(status="submitted", ...)`, create an admin user with an encrypted TOTP secret — mirror the TOTP setup in `test_attestor_applications.py`.)

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement the gate service**

```python
async def verify_kyc(
    db: AsyncSession, redis: Redis, admin: User,
    application_id: UUID, name_match: bool, totp_code: str,
) -> AttestorApplication:
    """Confirm KYC + name match, advancing a submitted application to Level 1.

    Raises:
        HTTPException(422): application not 'submitted', applicant KYC not
            verified, or name does not match.
    """
    now = datetime.now(UTC)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        locked_admin = await db.get(User, admin.id, with_for_update=True)
        await auth_service.verify_totp_for_sensitive_action(
            db=db, redis=redis, user=locked_admin, code=totp_code)
        application = await _load_locked_application(db, application_id)
        if application.status != "submitted":
            raise HTTPException(status_code=422,
                detail="Only submitted applications can be KYC-verified.")
        applicant = await db.get(User, application.user_id)
        if applicant is None or applicant.kyc_status != "verified":
            raise HTTPException(status_code=422, detail="Applicant KYC is not verified.")
        if not name_match:
            raise HTTPException(status_code=422, detail="KYC name does not match.")
        application.status = "identity_verified"
        application.kyc_verified_at = now
        application.kyc_name_match = True
        await write_audit(db=db, actor_id=admin.id, action="attestor_kyc_verified",
            target_type="attestor_application", target_id=application.id,
            metadata={"user_id": str(application.user_id)})
    return application
```

Add a private `_load_locked_application(db, application_id) -> AttestorApplication` helper (select `with_for_update`, 404 if missing) reused by all gate tasks. Add `AttestorKycVerifyRequest` to `schemas.py` and the router endpoint (admin-gated, `RedisClient`), mirroring `review_attestor_application`.

- [ ] **Step 4: Run, verify pass.**

- [ ] **Step 5: Commit** — `git commit -m "feat(attestation): KYC verify onboarding gate"`

---

### Task 6: Credential cross-check gate → professional_verified (Level 2–3)

**Files:** Modify `application_service.py`, `schemas.py`, `router.py`; Test `test_attestor_onboarding.py`.

**Interfaces:**
- Produces: `verify_credential(db, redis, admin, application_id, payload)`; endpoint `POST /v1/admin/attestor/applications/{id}/verify-credential`; schema `AttestorCredentialCheckRequest{credential_id: UUID, issuing_body: <body enum>, good_standing: bool, registry_reference: str, totp_code: str}`. Records cross-check fields on the named `Credential`; on `good_standing=True` advances `identity_verified → professional_verified`, sets `verification`-implied level (stored later at activation). `good_standing=False` → `422` "Credential not in good standing." Credential must belong to the applicant.

- [ ] **Step 1: Failing test** — seed an `identity_verified` application + a `Credential` for the applicant; assert POST returns 200, status `professional_verified`, and the credential row has `good_standing=True`, `registry_checked_by=admin`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** `verify_credential`: lock admin + TOTP; `_load_locked_application`; require status `identity_verified`; load credential by id where `user_id == application.user_id` (else 422); set `issuing_body`/`good_standing`/`registry_checked_at=now`/`registry_checked_by=admin.id`/`registry_reference`; if not good standing → 422; else `application.status="professional_verified"`; audit `attestor_credential_checked`. Add schema + router endpoint.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(attestation): credential cross-check gate"`

---

### Task 7: Trial assign + decide (stub) → expert_verified (Level 3–4)

**Files:** Modify `application_service.py` (or new `trial_service.py`), `schemas.py`, `router.py`; Test `test_attestor_onboarding.py`.

**Interfaces:**
- Produces: `assign_trial(db, redis, admin, application_id, seeded_framework_id, totp_code) -> AttestorTrial` (status `professional_verified` required; creates `AttestorTrial(status="assigned", attempt=N)`); `decide_trial(db, redis, admin, application_id, trial_id, passed, feedback, totp_code) -> AttestorApplication` — `passed=True` → application `expert_verified`, trial `passed`; `passed=False` → trial `failed`, attempt 1 keeps application `professional_verified` (retry allowed), attempt 2 → application `held`. Endpoints `POST .../{id}/trial` and `POST .../{id}/trial/{trial_id}/decide`.

- [ ] **Step 1: Failing tests** (three): assign creates trial; decide pass → expert_verified; decide fail twice → held (second `assign_trial` permitted only while not held; assert attempt=2 then `held`).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** the two functions with TOTP + locking + audit (`attestor_trial_assigned`, `attestor_trial_passed`, `attestor_trial_failed`, `attestor_application_held`). `attempt` for a new trial = `1 + count(existing trials for application)`, capped at 2 (3rd assign → 409 "Trial attempts exhausted; application held."). Add schemas + endpoints.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(attestation): stubbed trial calibration gate"`

---

### Task 8: CoI declaration submit + sign

**Files:** Modify `application_service.py`, `schemas.py`, `router.py`; Test `test_attestor_onboarding.py`.

**Interfaces:**
- Produces: `sign_coi(db, user, application_id, declarations) -> AttestorApplication`; endpoint `POST /v1/attestor/applications/{id}/coi` (owner-scoped, `CurrentUser`); schema `CoiDeclarationRequest{declarations: list[CoiEntry], accept_policy: bool}` where `CoiEntry{entity: str, entity_type: Literal["firm","fund","individual"], relationship: Literal["financial","advisory","employment"], within_24mo: bool}`. Sets `coi_declarations`, `coi_signed_at=now`, `coi_expires_at=now+365d`. `accept_policy` must be `True` else `422`. Does **not** change `status` (a prerequisite, not a gate); editable until ACTIVE.

- [ ] **Step 1: Failing test** — owner posts CoI with `accept_policy=True`; assert 200, `coi_signed_at` set, `coi_expires_at` ~1y later; `accept_policy=False` → 422.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** (owner check: application `user_id == user.id` else 404; any pre-active status allowed; audit `attestor_coi_signed` with **count only**, never entity contents). Add schemas + endpoint.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(attestation): CoI declaration sign"`

---

### Task 9: Payout method + tax document prerequisites

**Files:** Modify `application_service.py`, `schemas.py`, `router.py`; Test `test_attestor_onboarding.py`.

**Interfaces:**
- Produces: `attach_payout(db, user, application_id, payout_account_id) -> AttestorApplication` (verifies the `PayoutAccount` belongs to the user via `financials.models.PayoutAccount`, `deleted_at IS NULL`; sets `application.payout_account_id`); `set_tax_document(db, user, application_id, payload) -> AttestorApplicationResponse`-shaped — reuses the existing private upload-session pattern to issue a presigned POST for the tax doc and records `tax_document_type` + `tax_document_key`. Endpoints `POST /v1/attestor/applications/{id}/payout` and `POST /v1/attestor/applications/{id}/tax-document`.

**Note:** Reuse the upload-session mechanics already used for credential/report evidence (`AttestationUploadSession` + presigned POST helper in `credential_service`/`report`). Do not build a new storage path. Tax docs are private S3, virus-scanned, owner/admin-scoped only.

- [ ] **Step 1: Failing tests** — attach a payout account owned by the user → 200 + `payout_account_id` set; attaching another user's account → 404; request a tax-doc upload session → 201 with presigned `url`/`fields` and `tax_document_type` recorded.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** both functions (owner-scoped; audit `attestor_payout_attached`, `attestor_tax_document_set` — never log the key). Add schemas (`AttestorPayoutAttachRequest{payout_account_id: UUID}`, `AttestorTaxDocumentRequest{tax_document_type: Literal["w9","w8ben","other"], file_name, content_type, size_bytes}`) + endpoints.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(attestation): payout + tax document onboarding steps"`

---

### Task 10: Activation transition → ACTIVE (profile + role + level)

**Files:** Modify `application_service.py`, `schemas.py`, `router.py`; Test `test_attestor_onboarding.py`.

**Interfaces:**
- Consumes: all prior gate fields.
- Produces: `activate_attestor(db, redis, admin, application_id, totp_code) -> AttestorApplication`; endpoint `POST /v1/admin/attestor/applications/{id}/activate`. Requires `status == "expert_verified"` **and** all prerequisites present (`coi_signed_at`, `sectors`, `framework_categories`, `payout_account_id`, `tax_document_key`) — any missing → `422` naming what's absent. Creates/updates `AttestorProfile` (`active=True`, `verification_level=4`, copies `sectors`/`framework_categories`/`jurisdictions`/`coi_*`), grants the `attestor` `UserRole.approved_at`, sets `application.status="active"`. **Replaces** the approve branch of the old `review_application`.

- [ ] **Step 1: Failing tests** — full happy path: drive an application through submit → kyc → credential → trial-pass → coi → payout → tax, then activate → 200 status `active`, an `AttestorProfile(active=True, verification_level=4, sectors=[...])` exists, and a `UserRole(role="attestor", approved_at not null)` exists. Second test: activate with missing tax doc → 422 mentioning `tax_document`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** `activate_attestor` (rename/replace `_approve_attestor_profile_and_role` as `_create_active_profile`, now copying taxonomy + CoI + setting `verification_level=4`). Lock admin + TOTP; validate state + prerequisites; create profile + role; audit `attestor_activated`. Add schema (`AttestorActivateRequest{totp_code: str}`) + endpoint.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(attestation): activate attestor at end of onboarding"`

---

### Task 11: Public Attestor directory

**Files:** Create `backend/app/modules/attestation/directory_service.py`; Modify `schemas.py`, `router.py`; Test `test_attestor_onboarding.py`.

**Interfaces:**
- Consumes: `AttestorProfile` (active), `User.display_name`, verified `Credential`s, `Attestation` (completed count).
- Produces: `list_directory(db, *, sector, framework_category, jurisdiction, level) -> list[...]` and `get_directory_profile(db, user_id) -> ...`; endpoints `GET /v1/attestors` (filters as query params) and `GET /v1/attestors/{user_id}`; response schemas `AttestorDirectoryEntry{user_id, display_name, sectors, framework_categories, jurisdictions, verification_level, credentials: list[PublicCredentialResponse], completed_attestations: int, reputation: float | None}` and `AttestorDirectoryResponse{attestors: [...]}`. `reputation` is always `None` here (computed in Spec E). Only `active` profiles returned; **never** expose CoI, tax, payout, raw credential evidence/reference.

- [ ] **Step 1: Failing tests** — directory lists an active attestor with sectors + completed count; excludes a non-active (still-onboarding) attestor; filter `?sector=PE` returns only PE attestors; response JSON has no `coi`/`tax`/`payout`/`registry_reference` keys.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** `directory_service` (query active profiles + `&&` array filters when params given; completed count = `select count() from attestations where attestor_id=user_id and status in ('released','resolved','closed')`; credentials via existing `PublicCredentialResponse`, only `verification_status="verified"`). Public endpoints (no auth required — directory is public, SSR-friendly). Add schemas + router.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(attestation): public attestor directory"`

---

### Task 12: Retire legacy review endpoint, OpenAPI, client regen

**Files:** Modify `application_service.py`, `router.py`, `contracts/openapi.yaml`; Test `test_attestor_onboarding.py`, existing `test_attestor_applications.py`.

**Interfaces:**
- Removes: `POST /v1/admin/attestor/applications/{id}/review` and `review_application` approve branch (reject path preserved as `reject_application` → `POST .../{id}/reject` with `{feedback, totp_code}`).

- [ ] **Step 1: Failing test** — `POST .../review` returns 404 (route gone); `POST .../{id}/reject` with feedback + TOTP rejects a non-active application → 200 status `rejected`; rejecting without feedback → 422.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — extract the reject logic into `reject_application(db, redis, admin, application_id, feedback, totp_code)` (TOTP-gated; require non-terminal status; set `status="rejected"`, `admin_feedback`, `reviewed_by/at`; audit `attestor_application_rejected`). Remove the `review` endpoint + `AttestorApplicationReviewRequest` usage; add `AttestorApplicationRejectRequest{feedback: str (min 1), totp_code}` + `POST .../{id}/reject`. Update `list_attestor_applications_for_admin` `status` filter Literal to the new status set (`submitted|identity_verified|professional_verified|expert_verified|active|rejected|withdrawn|held`).
- [ ] **Step 4: Update `contracts/openapi.yaml`** — add all new endpoints (Tasks 4–12), remove `/review`. Then regenerate the frontend client: `cd frontend && pnpm generate:api`.
- [ ] **Step 5: Run full suite** — `uv run pytest tests/integration/test_attestor_onboarding.py tests/integration/test_attestor_applications.py -v`; then whole-repo gate `uv run ruff check .` and `uv run mypy app`.
- [ ] **Step 6: Commit** — `git commit -m "feat(attestation): finalize onboarding API, retire legacy review"`

---

## Self-Review

**Spec coverage:**
- 1.1 application form → Tasks 1,2,4 (legal_name, linkedin, body numbers, CV via tax/upload pattern, taxonomy). ✓
- 1.2 KYC → Level 1 → Task 5. ✓
- 1.3 credential cross-check → Level 2–3 → Task 6. ✓
- 1.4 CoI (24mo, annual) → Tasks 1,8 (`coi_expires_at = +365d`). ✓ (annual re-sign *enforcement* job deferred per spec open question — not in this plan.)
- 1.5 taxonomy → Tasks 1,3,4; over-tagging penalty deferred to Spec B (noted). ✓
- 1.6 trial (stub) → Tasks 1,2,7. ✓
- 1.7 payout + tax docs → Task 9 (reuses `PayoutAccount` + upload session). ✓
- 1.8 profile published + directory + levels → Tasks 10,11. ✓ (L5 Certified deferred to Spec E.)
- State machine + level field → Tasks 1,2,5,6,7,10. ✓
- PII never in directory → Task 11. ✓

**Gaps / deferred (intentional, from spec):** CV upload endpoint — folded into the upload-session pattern of Task 9; if CV needs its own endpoint, mirror Task 9's tax-document step (same mechanics). Annual CoI re-sign job and L5 Certified are explicitly out of this plan per the spec's deferral.

**Placeholder scan:** Migration, taxonomy, models, schemas, and the KYC gate carry full code. Tasks 6–12 specify exact function signatures, transitions, audit actions, endpoints, and test assertions, reusing the fully-shown Task 5 gate pattern (TOTP + `_load_locked_application` + status check + audit) — deliberately not re-pasting identical scaffolding, with the reused pattern named explicitly each time.

**Type consistency:** Status values (`submitted/identity_verified/professional_verified/expert_verified/active/held/rejected/withdrawn`), `verification_level` (int, max 4), enum names (`attestor_trial_status_enum`, `attestor_credential_body_enum`, `tax_document_type_enum`), and field names (`coi_declarations`, `sectors`, `framework_categories`, `payout_account_id`, `tax_document_key`) are identical across migration, models, schemas, services, and tests.
