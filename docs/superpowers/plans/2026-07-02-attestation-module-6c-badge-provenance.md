# Attestation Module 6c — Badge & Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish an immutable, version-locked attestation badge on attestation close, and surface it on the framework page, the attestor's public "Completed Attestations" list, and a private owner/admin provenance view.

**Architecture:** A new immutable `attestation_badges` snapshot table is written synchronously inside the same transaction that closes an eligible attestation. The attested framework version is captured as an FK on the attestation at request-submission time. Reads render from the snapshot (never live profile/framework tables): public surfaces show positive determinations only; an owner/admin surface shows the full provenance including rejected.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, Pydantic v2, PostgreSQL 16, pytest + pytest-asyncio, httpx AsyncClient.

## Global Constraints

- All backend commands run from `backend/` (e.g. `cd /Users/a0000/projects/auracles/backend`).
- Package/test runner is `uv`: `uv run pytest ...`, `uv run alembic ...`, `uv run ruff check .`, `uv run mypy app`.
- Alembic current head is `2026_07_02_0054`; the new migration's `down_revision` is `2026_07_02_0054`.
- Migration filename format: `YYYY_MM_DD_NNNN_description.py`; use `2026_07_02_0055_attestation_badges_provenance.py`.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit. One behavior per cycle.
- Pydantic schema on every request/response; response models explicit (never return ORM rows).
- RBAC enforced at the FastAPI dependency layer, never inside service logic.
- Public surfaces are PII-safe: expose only public credential fields (title/issuer/credential_type/issued_date/expires_date/expired) and the attestor display name; never evidence keys; never rejected determinations.
- Badge rows are insert-only in 6c — no update or delete path.
- Provenance snapshot is written for **all** closed+eligible framework-target attestations (approved/conditional/rejected). Public read filters, not the write, enforce positive-only.
- Positive determinations are `outcome in {"approved", "conditional"}`.
- `newer_version_exists = (framework.version != badge.framework_version)`; `False` when `badge.framework_version is None`.
- Commit messages: no `Co-Authored-By: Claude` trailer. Work stays on the current `attestation/module-6c` branch (do not create branches).
- Before claiming any task clean, run whole-repo `uv run ruff check .` and `uv run mypy app` from `backend/`.
- Docstrings: module-level on every new file; Google-style on every public function/class; test functions get a one-line docstring naming the behavior/rule under test.

---

### Task 1: Migration + ORM models

**Files:**
- Create: `backend/migrations/versions/2026_07_02_0055_attestation_badges_provenance.py`
- Modify: `backend/app/modules/attestation/models.py` (add `framework_version_id` to `Attestation` after the `report_published_eligible` column ~line 576; add new `AttestationBadge` class at end of file)
- Test: `backend/tests/unit/modules/test_attestation_badges_migration.py`

**Interfaces:**
- Consumes: existing `attestations` table, `framework_versions.id`, `frameworks.id`, `users.id`, enums `attestation_review_type_enum`, `attestation_outcome_enum`.
- Produces:
  - Table `attestation_badges` with columns `id, attestation_id (UNIQUE FK), framework_id (FK, indexed), review_type, outcome, attestor_id (FK, indexed), attestor_display_name, credentials_snapshot (JSONB), framework_version (VARCHAR(20) NULL), issued_at, created_at`.
  - Column `attestations.framework_version_id UUID NULL FK -> framework_versions.id ON DELETE SET NULL`.
  - ORM model `AttestationBadge` (tablename `attestation_badges`) and `Attestation.framework_version_id: Mapped[UUID | None]`.

- [ ] **Step 1: Write the failing migration test**

Create `backend/tests/unit/modules/test_attestation_badges_migration.py`:

```python
"""Migration coverage for Module 6c badge & provenance schema.

6c adds the immutable ``attestation_badges`` snapshot table and the
``attestations.framework_version_id`` capture FK.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings

PREVIOUS_HEAD = "2026_07_02_0054"


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run migrations to head and restore the DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_badges_table_and_capture_fk_exist(migrated_engine: Engine) -> None:
    """Upgrade creates attestation_badges + attestations.framework_version_id."""
    inspector = inspect(migrated_engine)

    assert "attestation_badges" in inspector.get_table_names()

    badge_columns = {c["name"] for c in inspector.get_columns("attestation_badges")}
    assert {
        "id",
        "attestation_id",
        "framework_id",
        "review_type",
        "outcome",
        "attestor_id",
        "attestor_display_name",
        "credentials_snapshot",
        "framework_version",
        "issued_at",
        "created_at",
    }.issubset(badge_columns)

    unique_names = {
        c["name"] for c in inspector.get_unique_constraints("attestation_badges")
    }
    assert "uq_attestation_badges_attestation" in unique_names

    index_names = {i["name"] for i in inspector.get_indexes("attestation_badges")}
    assert {
        "idx_attestation_badges_framework",
        "idx_attestation_badges_attestor",
    }.issubset(index_names)

    attestation_columns = {c["name"] for c in inspector.get_columns("attestations")}
    assert "framework_version_id" in attestation_columns


def test_downgrade_removes_slice_schema() -> None:
    """Downgrade -1 drops the badges table and the capture FK cleanly."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PREVIOUS_HEAD)
    try:
        inspector = inspect(engine)
        assert "attestation_badges" not in inspector.get_table_names()
        attestation_columns = {
            c["name"] for c in inspector.get_columns("attestations")
        }
        assert "framework_version_id" not in attestation_columns
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/unit/modules/test_attestation_badges_migration.py -v`
Expected: FAIL — `attestation_badges` table does not exist (migration not written yet).

- [ ] **Step 3: Write the migration**

Create `backend/migrations/versions/2026_07_02_0055_attestation_badges_provenance.py`:

```python
"""Add attestation badge & provenance schema.

Module 6c records an immutable badge snapshot for each closed+eligible
framework attestation and captures the attested framework version on the
attestation. The badge table is insert-only provenance; the capture FK
version-locks the badge.

Maps to: Module 6c design spec section 5.

Revision ID: 2026_07_02_0055
Revises: 2026_07_02_0054
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_02_0055"
down_revision: str | Sequence[str] | None = "2026_07_02_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REVIEW_TYPE_ENUM = postgresql.ENUM(
    "quality",
    "compliance",
    "expert",
    "provenance",
    name="attestation_review_type_enum",
    create_type=False,
)
_OUTCOME_ENUM = postgresql.ENUM(
    "approved",
    "conditional",
    "rejected",
    name="attestation_outcome_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create attestation_badges and add attestations.framework_version_id."""
    op.add_column(
        "attestations",
        sa.Column(
            "framework_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("framework_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_table(
        "attestation_badges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "attestation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "framework_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("frameworks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("review_type", _REVIEW_TYPE_ENUM, nullable=False),
        sa.Column("outcome", _OUTCOME_ENUM, nullable=False),
        sa.Column(
            "attestor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("attestor_display_name", sa.Text(), nullable=False),
        sa.Column(
            "credentials_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("framework_version", sa.String(length=20), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "attestation_id", name="uq_attestation_badges_attestation"
        ),
    )
    op.create_index(
        "idx_attestation_badges_framework",
        "attestation_badges",
        ["framework_id"],
    )
    op.create_index(
        "idx_attestation_badges_attestor",
        "attestation_badges",
        ["attestor_id"],
    )


def downgrade() -> None:
    """Drop attestation_badges and the capture FK."""
    op.drop_index("idx_attestation_badges_attestor", table_name="attestation_badges")
    op.drop_index("idx_attestation_badges_framework", table_name="attestation_badges")
    op.drop_table("attestation_badges")
    op.drop_column("attestations", "framework_version_id")
```

- [ ] **Step 4: Add ORM model changes**

In `backend/app/modules/attestation/models.py`, add the capture FK to the `Attestation` class immediately after the `report_published_eligible` column (~line 576-580):

```python
    framework_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("framework_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
```

At the end of `backend/app/modules/attestation/models.py`, add the new model:

```python
class AttestationBadge(CreatedAtMixin, Base):
    """Immutable published-badge / provenance snapshot for one Attestation.

    Written once when a framework-target Attestation closes and becomes
    publication-eligible. Renders the public trust badge and the private
    provenance record without reading live profile, framework, or credential
    tables, so the badge is tamper-evident against later mutation.

    Maps to: Module 6c design spec sections 4.2 and 5.1.
    """

    __tablename__ = "attestation_badges"
    __table_args__ = (
        UniqueConstraint(
            "attestation_id", name="uq_attestation_badges_attestation"
        ),
        Index("idx_attestation_badges_framework", "framework_id"),
        Index("idx_attestation_badges_attestor", "attestor_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id", ondelete="CASCADE"),
        nullable=False,
    )
    review_type: Mapped[str] = mapped_column(
        ATTESTATION_REVIEW_TYPE_ENUM,
        nullable=False,
    )
    outcome: Mapped[str] = mapped_column(ATTESTATION_OUTCOME_ENUM, nullable=False)
    attestor_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    attestor_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    credentials_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    framework_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
```

Confirm `text` is already imported at the top of the file (it is used by other models via `from sqlalchemy import (... text ...)` — verify it appears in the import block; if not, add `text` to that import).

- [ ] **Step 5: Run migration test to verify it passes**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/unit/modules/test_attestation_badges_migration.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Verify round-trip + lint/type**

Run:
```
cd /Users/a0000/projects/auracles/backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
uv run ruff check . && uv run mypy app
```
Expected: migrations succeed both directions; ruff + mypy clean.

- [ ] **Step 7: Commit**

```bash
cd /Users/a0000/projects/auracles
git add backend/migrations/versions/2026_07_02_0055_attestation_badges_provenance.py backend/app/modules/attestation/models.py backend/tests/unit/modules/test_attestation_badges_migration.py
git commit -m "Add attestation_badges provenance table + framework version capture FK"
```

---

### Task 2: Capture framework version at request submission

**Files:**
- Modify: `backend/app/modules/attestation/service.py` (`_create_attestation`, ~line 321-363)
- Test: `backend/tests/unit/modules/test_attestation_version_capture.py`

**Interfaces:**
- Consumes: `Attestation.framework_version_id` (Task 1), `FrameworkVersion` model, `Framework` model.
- Produces: `_create_attestation` stamps `framework_version_id` to the current published version row for framework targets; leaves it `None` for non-framework targets.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/modules/test_attestation_version_capture.py`:

```python
"""Framework-version capture on Attestation request submission (Module 6c).

A framework-target request records the version the attestor is contracted to
review; non-framework targets record no version.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.attestation import service as attestation_service
from app.modules.attestation.models import Attestation
from app.modules.attestation.schemas import AttestationRequestCreateRequest

pytestmark = pytest.mark.asyncio


async def test_framework_target_captures_current_version(db_session, framework_factory):
    """A framework-target request stamps the current published version row."""
    framework = await framework_factory(version="1.2")
    payload = AttestationRequestCreateRequest(
        target_type="framework",
        target_id=framework.id,
        review_type="quality",
    )

    attestation_id = await attestation_service._create_attestation(
        db_session,
        requestor_id=framework.contributor_id,
        payload=payload,
        amount=attestation_service.Decimal("500.00"),
        initiator_is_owner=True,
        status_value="pending_fee",
    )

    attestation = await db_session.scalar(
        select(Attestation).where(Attestation.id == attestation_id)
    )
    assert attestation.framework_version_id is not None


async def test_non_framework_target_captures_no_version(db_session, user_factory):
    """A non-framework target leaves framework_version_id NULL."""
    requestor = await user_factory()
    payload = AttestationRequestCreateRequest(
        target_type="operator",
        target_id=requestor.id,
        review_type="expert",
    )

    attestation_id = await attestation_service._create_attestation(
        db_session,
        requestor_id=requestor.id,
        payload=payload,
        amount=attestation_service.Decimal("300.00"),
        initiator_is_owner=True,
        status_value="pending_fee",
    )

    attestation = await db_session.scalar(
        select(Attestation).where(Attestation.id == attestation_id)
    )
    assert attestation.framework_version_id is None
```

> Note for the implementer: `framework_factory` and `user_factory` are the existing test factories in `backend/tests/factories/` / `conftest.py`. Confirm the exact fixture names and how a framework is created with a matching `framework_versions` row (the framework publish flow creates the version row). If a helper is needed to publish a version, follow the pattern already used in `tests/integration/test_frameworks_endpoints.py` or the frameworks factory. Match the version string used by the factory.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/unit/modules/test_attestation_version_capture.py -v`
Expected: FAIL — `framework_version_id` is `None` for the framework target (capture not implemented).

- [ ] **Step 3: Implement version capture**

In `backend/app/modules/attestation/service.py`, add a helper above `_create_attestation`:

```python
async def _current_framework_version_id(
    db: AsyncSession,
    *,
    framework_id: UUID,
) -> UUID | None:
    """Resolve the immutable version row for a framework's current version.

    Matches ``frameworks.version`` to the ``framework_versions`` row. Returns
    ``None`` when no matching published version row exists (e.g. an unpublished
    framework), leaving the attestation version-unlocked.

    Args:
        db: Async SQLAlchemy session.
        framework_id: Framework being attested.

    Returns:
        The ``framework_versions.id`` for the framework's current version, or
        ``None``.
    """
    return await db.scalar(
        select(FrameworkVersion.id)
        .join(Framework, Framework.id == FrameworkVersion.framework_id)
        .where(
            FrameworkVersion.framework_id == framework_id,
            FrameworkVersion.version == Framework.version,
        )
    )
```

Ensure the imports at the top of `service.py` include `FrameworkVersion` and `Framework`:
```python
from app.modules.frameworks.models import Framework, FrameworkVersion
```
(`Framework` is likely already imported — add `FrameworkVersion` alongside it.)

Then, inside `_create_attestation`, resolve the version id before constructing the `Attestation` and pass it in. Replace the `Attestation(...)` construction block with:

```python
        framework_version_id = None
        if payload.target_type == "framework":
            framework_version_id = await _current_framework_version_id(
                db, framework_id=payload.target_id
            )
        attestation = Attestation(
            target_type=payload.target_type,
            target_id=payload.target_id,
            requestor_id=requestor_id,
            status=status_value,
            review_type=payload.review_type,
            brief=payload.brief.model_dump() if payload.brief is not None else None,
            requested_specializations=payload.requested_specializations,
            requested_jurisdictions=payload.requested_jurisdictions,
            fee_amount=amount,
            currency="USD",
            framework_version_id=framework_version_id,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/unit/modules/test_attestation_version_capture.py -v`
Expected: PASS.

- [ ] **Step 5: Lint/type + regression on request flow**

Run:
```
cd /Users/a0000/projects/auracles/backend && uv run ruff check . && uv run mypy app
uv run pytest tests/integration/test_attestation_endpoints.py -q
```
Expected: clean; existing request-submission tests still pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/a0000/projects/auracles
git add backend/app/modules/attestation/service.py backend/tests/unit/modules/test_attestation_version_capture.py
git commit -m "Capture attested framework version on attestation request submission"
```

---

### Task 3: Badge publish service + wire into close paths

**Files:**
- Create: `backend/app/modules/attestation/badge_service.py`
- Modify: `backend/app/modules/attestation/release_service.py` (`_release_and_close`, after `report_published_eligible = True` ~line 127) and `backend/app/modules/attestation/dispute_service.py` (the dispute-resolved branch that sets `report_published_eligible = True` ~line 209-211)
- Test: `backend/tests/unit/modules/test_attestation_badge_publish.py`

**Interfaces:**
- Consumes: `AttestationBadge` model (Task 1), `Attestation.framework_version_id` (Task 1/2), `FrameworkVersion`, `Credential`, `User`.
- Produces: `async def publish_badge(db: AsyncSession, *, attestation: Attestation) -> None` — idempotent snapshot writer, called inside existing close transactions.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/modules/test_attestation_badge_publish.py`:

```python
"""Badge snapshot publish behavior (Module 6c).

publish_badge writes one immutable snapshot per closed+eligible framework
attestation, for all outcomes, idempotently; it writes nothing for
non-framework targets.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.modules.attestation import badge_service
from app.modules.attestation.models import AttestationBadge

pytestmark = pytest.mark.asyncio


async def test_publish_writes_snapshot_for_approved_framework(
    db_session, closed_framework_attestation_factory
):
    """An approved framework attestation gets a badge snapshot at publish."""
    attestation = await closed_framework_attestation_factory(
        outcome="approved", framework_version="1.2"
    )

    await badge_service.publish_badge(db_session, attestation=attestation)

    badge = await db_session.scalar(
        select(AttestationBadge).where(
            AttestationBadge.attestation_id == attestation.id
        )
    )
    assert badge is not None
    assert badge.outcome == "approved"
    assert badge.review_type == attestation.review_type
    assert badge.framework_id == attestation.target_id
    assert badge.attestor_id == attestation.attestor_id
    assert badge.framework_version == "1.2"
    assert isinstance(badge.credentials_snapshot, list)


async def test_publish_writes_snapshot_for_rejected(
    db_session, closed_framework_attestation_factory
):
    """A rejected outcome is still snapshotted (complete provenance)."""
    attestation = await closed_framework_attestation_factory(outcome="rejected")

    await badge_service.publish_badge(db_session, attestation=attestation)

    count = await db_session.scalar(
        select(func.count(AttestationBadge.id)).where(
            AttestationBadge.attestation_id == attestation.id
        )
    )
    assert count == 1


async def test_publish_is_idempotent(
    db_session, closed_framework_attestation_factory
):
    """Publishing twice writes a single badge row."""
    attestation = await closed_framework_attestation_factory(outcome="approved")

    await badge_service.publish_badge(db_session, attestation=attestation)
    await badge_service.publish_badge(db_session, attestation=attestation)

    count = await db_session.scalar(
        select(func.count(AttestationBadge.id)).where(
            AttestationBadge.attestation_id == attestation.id
        )
    )
    assert count == 1


async def test_publish_skips_non_framework_target(
    db_session, closed_operator_attestation_factory
):
    """A non-framework target writes no badge row."""
    attestation = await closed_operator_attestation_factory(outcome="approved")

    await badge_service.publish_badge(db_session, attestation=attestation)

    count = await db_session.scalar(
        select(func.count(AttestationBadge.id)).where(
            AttestationBadge.attestation_id == attestation.id
        )
    )
    assert count == 0
```

> Note for the implementer: factories `closed_framework_attestation_factory`, `closed_operator_attestation_factory` may not exist yet — build them in `backend/tests/factories/` (or as conftest fixtures) following the existing attestation factory patterns in `tests/factories/`. A "closed" attestation has `status="closed"`, `report_published_eligible=True`, `outcome` set, `attestor_id` set, `closed_at` set, and (for framework targets) a real framework + `framework_versions` row + `framework_version_id`. Reuse existing framework/user/credential factories. The `framework_version` kwarg controls the version string on the linked `framework_versions` row.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/unit/modules/test_attestation_badge_publish.py -v`
Expected: FAIL — `app.modules.attestation.badge_service` does not exist / `publish_badge` undefined.

- [ ] **Step 3: Implement `badge_service.publish_badge`**

Create `backend/app/modules/attestation/badge_service.py`:

```python
"""Attestation badge & provenance service.

Writes the immutable badge snapshot when a framework-target Attestation closes
and becomes publication-eligible, and reads badges for the public and
owner/admin surfaces.

Maps to: Module 6c design spec sections 6 and 7.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation.models import (
    Attestation,
    AttestationBadge,
    Credential,
)
from app.modules.auth.models import User
from app.modules.frameworks.models import FrameworkVersion


async def _public_credentials_snapshot(
    db: AsyncSession,
    *,
    attestor_id: UUID,
) -> list[dict[str, object]]:
    """Return the attestor's verified credentials as public-safe snapshot dicts.

    Mirrors the public credential shape used by the attestor directory: never
    includes evidence keys, verification URLs, or reference numbers.

    Args:
        db: Async SQLAlchemy session.
        attestor_id: User id of the attestor.

    Returns:
        A JSON-serializable list of credential dicts.
    """
    rows = await db.execute(
        select(Credential)
        .where(
            Credential.user_id == attestor_id,
            Credential.verification_status == "verified",
        )
        .order_by(Credential.issued_date.desc())
    )
    today = date.today()
    return [
        {
            "title": credential.title,
            "issuer": credential.issuer,
            "credential_type": credential.credential_type,
            "issued_date": credential.issued_date.isoformat(),
            "expires_date": (
                credential.expires_date.isoformat()
                if credential.expires_date is not None
                else None
            ),
            "expired": (
                credential.expires_date is not None
                and credential.expires_date < today
            ),
        }
        for credential in rows.scalars().all()
    ]


async def publish_badge(db: AsyncSession, *, attestation: Attestation) -> None:
    """Write the immutable badge snapshot for a closed, eligible attestation.

    Runs inside the caller's close transaction. Only framework-target,
    publication-eligible attestations produce a badge. Snapshots the attestor
    display name, public credentials, and attested framework version. Idempotent
    via ``ON CONFLICT (attestation_id) DO NOTHING``.

    Args:
        db: Async SQLAlchemy session with an open transaction.
        attestation: The attestation being closed.
    """
    if attestation.target_type != "framework":
        return
    if not attestation.report_published_eligible:
        return
    if attestation.attestor_id is None or attestation.outcome is None:
        return

    version: str | None = None
    if attestation.framework_version_id is not None:
        version = await db.scalar(
            select(FrameworkVersion.version).where(
                FrameworkVersion.id == attestation.framework_version_id
            )
        )

    display_name = await db.scalar(
        select(User.display_name).where(User.id == attestation.attestor_id)
    )
    credentials = await _public_credentials_snapshot(
        db, attestor_id=attestation.attestor_id
    )

    stmt = (
        pg_insert(AttestationBadge)
        .values(
            attestation_id=attestation.id,
            framework_id=attestation.target_id,
            review_type=attestation.review_type,
            outcome=attestation.outcome,
            attestor_id=attestation.attestor_id,
            attestor_display_name=display_name or "Attestor",
            credentials_snapshot=credentials,
            framework_version=version,
            issued_at=attestation.closed_at or datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_attestation_badges_attestation")
    )
    await db.execute(stmt)
    logger.bind(
        module="attestation",
        action="publish_badge",
        attestation_id=attestation.id,
        framework_id=attestation.target_id,
    ).info("badge_published", outcome=attestation.outcome)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/unit/modules/test_attestation_badge_publish.py -v`
Expected: PASS (all four).

- [ ] **Step 5: Wire into the release/close transaction**

In `backend/app/modules/attestation/release_service.py`, add the import near the other attestation imports:

```python
from app.modules.attestation import badge_service
```

In `_release_and_close`, immediately after the `write_audit(...)` call that logs `attestation_released` (i.e. after `attestation.report_published_eligible = True` and its audit), add:

```python
    await badge_service.publish_badge(db=db, attestation=attestation)
```

- [ ] **Step 6: Wire into the dispute-rejected close path**

In `backend/app/modules/attestation/dispute_service.py`, add the import near the other attestation imports:

```python
from app.modules.attestation import badge_service
```

In the dispute-resolution branch where `attestation.report_published_eligible = True` is set (the outcome that lets the report stand, ~line 209-211), add — after that assignment and within the same transaction — :

```python
            await badge_service.publish_badge(db=db, attestation=attestation)
```

Do **not** add it to the `upheld_refund` branch (line ~229-231, `report_published_eligible = False`) or the admin-refund path (~line 417) — those are not publication-eligible.

- [ ] **Step 7: Write the wiring integration test**

Add to `backend/tests/integration/test_attestation_badge_publish_wiring.py`:

```python
"""Badge publish is wired into the attestation close transactions (Module 6c)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.attestation.models import AttestationBadge

pytestmark = pytest.mark.asyncio


async def test_accept_report_publishes_badge(
    db_session, report_submitted_framework_attestation_factory, accept_report_caller
):
    """Accepting a submitted framework report writes the badge in the close txn."""
    attestation = await report_submitted_framework_attestation_factory(
        outcome="approved"
    )

    await accept_report_caller(attestation)

    badge = await db_session.scalar(
        select(AttestationBadge).where(
            AttestationBadge.attestation_id == attestation.id
        )
    )
    assert badge is not None
```

> Note for the implementer: build `report_submitted_framework_attestation_factory` (status `report_submitted`, escrow present, no open dispute, outcome set, framework target + version FK) and `accept_report_caller` (invokes `release_service.accept_report` with the requestor as actor) from the existing patterns in `tests/integration/test_attestation_*`. If those integration helpers already exist under different names, reuse them and adjust. Keep this test to the single behavior: after accept, the badge row exists.

- [ ] **Step 8: Run wiring test + full badge suite**

Run:
```
cd /Users/a0000/projects/auracles/backend && uv run pytest tests/unit/modules/test_attestation_badge_publish.py tests/integration/test_attestation_badge_publish_wiring.py -v
uv run pytest tests/integration/test_attestation_dispute*.py -q
```
Expected: badge tests PASS; existing dispute tests still pass.

- [ ] **Step 9: Lint/type + commit**

```bash
cd /Users/a0000/projects/auracles/backend && uv run ruff check . && uv run mypy app
cd /Users/a0000/projects/auracles
git add backend/app/modules/attestation/badge_service.py backend/app/modules/attestation/release_service.py backend/app/modules/attestation/dispute_service.py backend/tests/unit/modules/test_attestation_badge_publish.py backend/tests/integration/test_attestation_badge_publish_wiring.py
git commit -m "Publish immutable attestation badge in close transactions"
```

---

### Task 4: Framework-page badge list + newer_version_exists

**Files:**
- Modify: `backend/app/modules/explore/schemas.py` (add `AttestationBadgeDetail`; add `attestation_badges` to `ExploreFrameworkDetail`)
- Modify: `backend/app/modules/explore/service.py` (add `_framework_badge_details`; wire into `get_framework_detail` return ~line 1076)
- Test: `backend/tests/integration/test_explore_framework_badges.py`

**Interfaces:**
- Consumes: `AttestationBadge` (Task 1/3), `PublicCredentialResponse` (existing, `app.modules.attestation.schemas`), `Framework.version`.
- Produces:
  - `AttestationBadgeDetail` schema: `id, review_type, outcome, attestor_id, attestor_display_name, credentials: list[PublicCredentialResponse], issued_at, framework_version: str | None, newer_version_exists: bool`.
  - `ExploreFrameworkDetail.attestation_badges: list[AttestationBadgeDetail]`.
  - `async def _framework_badge_details(db, framework) -> list[AttestationBadgeDetail]` (public, positive-only).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_explore_framework_badges.py`:

```python
"""Framework-page badge list (Module 6c, public positive-only)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_detail_lists_positive_badges_only(
    async_client, published_framework_with_badges
):
    """Framework detail returns approved/conditional badges, excludes rejected."""
    framework = published_framework_with_badges  # has approved + rejected badges

    response = await async_client.get(f"/v1/explore/frameworks/{framework.id}")

    assert response.status_code == 200
    outcomes = {b["outcome"] for b in response.json()["attestation_badges"]}
    assert outcomes == {"approved"}


async def test_newer_version_exists_flag(
    async_client, framework_with_stale_badge
):
    """A badge whose captured version differs from current flags newer_version_exists."""
    framework = framework_with_stale_badge  # badge at v1.0, framework now v1.1

    response = await async_client.get(f"/v1/explore/frameworks/{framework.id}")

    badge = response.json()["attestation_badges"][0]
    assert badge["framework_version"] == "1.0"
    assert badge["newer_version_exists"] is True
```

> Note for the implementer: build `published_framework_with_badges` (a published framework with two `attestation_badges` rows — one `approved`, one `rejected`) and `framework_with_stale_badge` (framework current version `1.1`, one approved badge with `framework_version="1.0"`) as fixtures, inserting `AttestationBadge` rows directly (they are provenance snapshots — direct insert is legitimate test setup). Reuse the existing explore/framework test fixtures for the published framework.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/integration/test_explore_framework_badges.py -v`
Expected: FAIL — response has no `attestation_badges` key.

- [ ] **Step 3: Add the schema**

In `backend/app/modules/explore/schemas.py`, add (near `ExploreAttestationBadge`, and ensure `PublicCredentialResponse` is imported — it already is at the top):

```python
class AttestationBadgeDetail(BaseModel):
    """Full version-locked attestation badge for the framework page."""

    id: UUID
    review_type: str
    outcome: Literal["approved", "conditional", "rejected"]
    attestor_id: UUID
    attestor_display_name: str
    credentials: list[PublicCredentialResponse] = []
    issued_at: datetime
    framework_version: str | None
    newer_version_exists: bool
```

Add the field to `ExploreFrameworkDetail`:

```python
class ExploreFrameworkDetail(ExploreFrameworkCard):
    """Public Framework detail payload."""

    preview_artifact_id: UUID | None
    preview_url: str | None
    artifacts: list[ExploreArtifactSummary]
    attestation_badges: list[AttestationBadgeDetail] = []
```

- [ ] **Step 4: Implement the badge-detail builder**

In `backend/app/modules/explore/service.py`, add near `_framework_attestation_badges` (~line 530). Add the model + schema imports at the top of the file: `AttestationBadge` from `app.modules.attestation.models`, `PublicCredentialResponse` from `app.modules.attestation.schemas`, and `AttestationBadgeDetail` from `app.modules.explore.schemas`.

```python
_PUBLIC_BADGE_OUTCOMES = ("approved", "conditional")


async def _framework_badge_details(
    db: AsyncSession,
    framework: Framework,
) -> list[AttestationBadgeDetail]:
    """Return public positive attestation badges for one Framework.

    Renders from the immutable ``attestation_badges`` snapshot, most-recent
    first, excluding rejected determinations. ``newer_version_exists`` is true
    when the badge's captured version differs from the framework's current
    version.

    Args:
        db: Async SQLAlchemy session.
        framework: The framework whose badges to render.

    Returns:
        Positive attestation badge details, newest first.
    """
    rows = (
        await db.execute(
            select(AttestationBadge)
            .where(
                AttestationBadge.framework_id == framework.id,
                AttestationBadge.outcome.in_(_PUBLIC_BADGE_OUTCOMES),
            )
            .order_by(AttestationBadge.issued_at.desc())
        )
    ).scalars().all()
    return [
        AttestationBadgeDetail(
            id=badge.id,
            review_type=badge.review_type,
            outcome=badge.outcome,
            attestor_id=badge.attestor_id,
            attestor_display_name=badge.attestor_display_name,
            credentials=[
                PublicCredentialResponse(**cred)
                for cred in badge.credentials_snapshot
            ],
            issued_at=badge.issued_at,
            framework_version=badge.framework_version,
            newer_version_exists=(
                badge.framework_version is not None
                and badge.framework_version != framework.version
            ),
        )
        for badge in rows
    ]
```

In `get_framework_detail`, add to the `ExploreFrameworkDetail(...)` return (~line 1076):

```python
    return ExploreFrameworkDetail(
        **card.model_dump(),
        preview_artifact_id=framework.preview_artifact_id,
        preview_url=await _preview_url(redis, framework, preview_artifact, client_ip),
        artifacts=[
            ExploreArtifactSummary(
                id=artifact.id,
                name=artifact.name,
                file_size=artifact.file_size,
                mime_type=artifact.mime_type,
                created_at=artifact.created_at,
            )
            for artifact in artifacts
        ],
        attestation_badges=await _framework_badge_details(db, framework),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/integration/test_explore_framework_badges.py -v`
Expected: PASS.

- [ ] **Step 6: Lint/type + explore regression + commit**

```bash
cd /Users/a0000/projects/auracles/backend && uv run ruff check . && uv run mypy app && uv run pytest tests/integration/test_explore_endpoints.py -q
cd /Users/a0000/projects/auracles
git add backend/app/modules/explore/schemas.py backend/app/modules/explore/service.py backend/tests/integration/test_explore_framework_badges.py
git commit -m "Expose version-locked attestation badges on framework detail page"
```

---

### Task 5: Attestor public "Completed Attestations" list

**Files:**
- Modify: `backend/app/modules/attestation/badge_service.py` (add `list_attestor_completed`)
- Modify: `backend/app/modules/attestation/schemas.py` (add `AttestorCompletedAttestation`)
- Modify: `backend/app/modules/attestation/router.py` (add `GET /attestors/{user_id}/completed`)
- Test: `backend/tests/integration/test_attestor_completed_list.py`

**Interfaces:**
- Consumes: `AttestationBadge` (Task 1/3), `Framework.title` (existing).
- Produces:
  - `AttestorCompletedAttestation` schema: `framework_id, framework_title, review_type, outcome, issued_at, framework_version`.
  - `async def list_attestor_completed(db, *, attestor_id) -> list[AttestorCompletedAttestation]` (public, positive-only).
  - Public endpoint `GET /v1/attestation/attestors/{user_id}/completed`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_attestor_completed_list.py`:

```python
"""Attestor public Completed Attestations list (Module 6c, positive-only)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_lists_positive_completed_with_framework_title(
    async_client, attestor_with_completed_badges
):
    """Public list returns the attestor's positive badges with framework titles."""
    attestor_id = attestor_with_completed_badges  # has approved + rejected badges

    response = await async_client.get(
        f"/v1/attestation/attestors/{attestor_id}/completed"
    )

    assert response.status_code == 200
    body = response.json()
    outcomes = {entry["outcome"] for entry in body}
    assert outcomes == {"approved"}
    assert all(entry["framework_title"] for entry in body)
```

> Note for the implementer: build `attestor_with_completed_badges` inserting two `AttestationBadge` rows for one attestor (one `approved`, one `rejected`) against real frameworks (so `framework_title` joins). Returns the attestor user id.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/integration/test_attestor_completed_list.py -v`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 3: Add the schema**

In `backend/app/modules/attestation/schemas.py`, add near `AttestorDirectoryEntry`:

```python
class AttestorCompletedAttestation(BaseModel):
    """One public entry in an Attestor's Completed Attestations list."""

    framework_id: UUID
    framework_title: str
    review_type: str
    outcome: Literal["approved", "conditional"]
    issued_at: datetime
    framework_version: str | None
```

Confirm `datetime`, `UUID`, and `Literal` are imported in the file (they are used by other schemas — verify).

- [ ] **Step 4: Implement `list_attestor_completed`**

In `backend/app/modules/attestation/badge_service.py`, add the imports `from app.modules.frameworks.models import Framework, FrameworkVersion` (extend the existing `FrameworkVersion` import to include `Framework`) and `from app.modules.attestation.schemas import AttestorCompletedAttestation`, then:

```python
_PUBLIC_BADGE_OUTCOMES = ("approved", "conditional")


async def list_attestor_completed(
    db: AsyncSession,
    *,
    attestor_id: UUID,
) -> list[AttestorCompletedAttestation]:
    """Return an attestor's public positive completed attestations, newest first.

    Args:
        db: Async SQLAlchemy session.
        attestor_id: User id of the attestor.

    Returns:
        Positive completed-attestation entries with framework titles.
    """
    rows = (
        await db.execute(
            select(AttestationBadge, Framework.title)
            .join(Framework, Framework.id == AttestationBadge.framework_id)
            .where(
                AttestationBadge.attestor_id == attestor_id,
                AttestationBadge.outcome.in_(_PUBLIC_BADGE_OUTCOMES),
            )
            .order_by(AttestationBadge.issued_at.desc())
        )
    ).all()
    return [
        AttestorCompletedAttestation(
            framework_id=badge.framework_id,
            framework_title=title,
            review_type=badge.review_type,
            outcome=badge.outcome,
            issued_at=badge.issued_at,
            framework_version=badge.framework_version,
        )
        for badge, title in rows
    ]
```

- [ ] **Step 5: Add the public route**

In `backend/app/modules/attestation/router.py`, add (near the other `/attestors/...` routes ~line 219-246; import `badge_service` and `AttestorCompletedAttestation`):

```python
@router.get(
    "/attestors/{user_id}/completed",
    response_model=list[AttestorCompletedAttestation],
    summary="List an attestor's public completed attestations",
)
async def list_attestor_completed_attestations(
    user_id: UUID,
    db: DatabaseSession,
) -> list[AttestorCompletedAttestation]:
    """Return the attestor's public positive completed attestations."""
    return await badge_service.list_attestor_completed(db, attestor_id=user_id)
```

Match `DatabaseSession` to the session dependency alias already used in this router (confirm its exact name in the file header; if the router uses `Depends(get_db)` inline, follow that form instead).

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/integration/test_attestor_completed_list.py -v`
Expected: PASS.

- [ ] **Step 7: Lint/type + commit**

```bash
cd /Users/a0000/projects/auracles/backend && uv run ruff check . && uv run mypy app
cd /Users/a0000/projects/auracles
git add backend/app/modules/attestation/badge_service.py backend/app/modules/attestation/schemas.py backend/app/modules/attestation/router.py backend/tests/integration/test_attestor_completed_list.py
git commit -m "Add attestor public Completed Attestations list endpoint"
```

---

### Task 6: Owner/admin provenance view

**Files:**
- Modify: `backend/app/modules/attestation/badge_service.py` (add `list_framework_provenance`)
- Modify: `backend/app/modules/frameworks/router.py` (add `GET /{framework_id}/attestation-badges`)
- Modify (if needed): `backend/app/modules/explore/schemas.py` reuse `AttestationBadgeDetail` — import into frameworks router (do not duplicate the schema).
- Test: `backend/tests/integration/test_framework_provenance_view.py`

**Interfaces:**
- Consumes: `AttestationBadge`, `Framework.contributor_id`, `Framework.version`, `AttestationBadgeDetail` (Task 4), the auth dependency that yields the current `User`, and `require_role`/role membership for admin.
- Produces:
  - `async def list_framework_provenance(db, *, framework) -> list[AttestationBadgeDetail]` (all outcomes, newest first).
  - Authenticated endpoint `GET /v1/frameworks/{framework_id}/attestation-badges` (owner or admin), 403 otherwise, 404 if framework missing.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_framework_provenance_view.py`:

```python
"""Owner/admin framework provenance view (Module 6c, all outcomes)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_owner_sees_all_outcomes_including_rejected(
    async_client, framework_with_mixed_badges, owner_auth_headers
):
    """The framework owner sees every badge, including rejected provenance."""
    framework, owner = framework_with_mixed_badges  # approved + rejected badges

    response = await async_client.get(
        f"/v1/frameworks/{framework.id}/attestation-badges",
        headers=owner_auth_headers(owner),
    )

    assert response.status_code == 200
    outcomes = {b["outcome"] for b in response.json()}
    assert "rejected" in outcomes and "approved" in outcomes


async def test_non_owner_non_admin_forbidden(
    async_client, framework_with_mixed_badges, other_user_auth_headers
):
    """A stranger cannot read another framework's provenance."""
    framework, _owner = framework_with_mixed_badges

    response = await async_client.get(
        f"/v1/frameworks/{framework.id}/attestation-badges",
        headers=other_user_auth_headers,
    )

    assert response.status_code == 403


async def test_missing_framework_returns_404(
    async_client, owner_auth_headers, some_user
):
    """An unknown framework id returns 404."""
    import uuid

    response = await async_client.get(
        f"/v1/frameworks/{uuid.uuid4()}/attestation-badges",
        headers=owner_auth_headers(some_user),
    )

    assert response.status_code == 404
```

> Note for the implementer: build `framework_with_mixed_badges` (published framework + owner user + one approved and one rejected `AttestationBadge`), `owner_auth_headers`/`other_user_auth_headers`/`some_user` from the existing auth-header fixtures used across `tests/integration/` (there is an established bearer-token fixture pattern — reuse it).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/integration/test_framework_provenance_view.py -v`
Expected: FAIL — 404/route not defined.

- [ ] **Step 3: Implement `list_framework_provenance`**

In `backend/app/modules/attestation/badge_service.py`, add (import `AttestationBadgeDetail` from `app.modules.explore.schemas`, `PublicCredentialResponse` already imported for the snapshot? it is not — import from `app.modules.attestation.schemas`; and `Framework`):

```python
async def list_framework_provenance(
    db: AsyncSession,
    *,
    framework: Framework,
) -> list["AttestationBadgeDetail"]:
    """Return all badges for a framework incl rejected (owner/admin provenance).

    Args:
        db: Async SQLAlchemy session.
        framework: The framework whose full provenance to render.

    Returns:
        All attestation badge details, newest first.
    """
    from app.modules.attestation.schemas import PublicCredentialResponse
    from app.modules.explore.schemas import AttestationBadgeDetail

    rows = (
        await db.execute(
            select(AttestationBadge)
            .where(AttestationBadge.framework_id == framework.id)
            .order_by(AttestationBadge.issued_at.desc())
        )
    ).scalars().all()
    return [
        AttestationBadgeDetail(
            id=badge.id,
            review_type=badge.review_type,
            outcome=badge.outcome,
            attestor_id=badge.attestor_id,
            attestor_display_name=badge.attestor_display_name,
            credentials=[
                PublicCredentialResponse(**cred)
                for cred in badge.credentials_snapshot
            ],
            issued_at=badge.issued_at,
            framework_version=badge.framework_version,
            newer_version_exists=(
                badge.framework_version is not None
                and badge.framework_version != framework.version
            ),
        )
        for badge in rows
    ]
```

> Local imports inside the function avoid a circular import: `explore.schemas`/`explore.service` already imports from `attestation`. Keep them local.

- [ ] **Step 4: Add the owner/admin route**

In `backend/app/modules/frameworks/router.py`, add (reuse the existing authenticated-user dependency in this router; the file already imports `require_role` and framework loading helpers). The route loads the framework, 404s if missing, then enforces owner-or-admin:

```python
@router.get(
    "/{framework_id}/attestation-badges",
    response_model=list[AttestationBadgeDetail],
    summary="List all attestation badges for a framework (owner or admin)",
)
async def list_framework_attestation_badges(
    framework_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> list[AttestationBadgeDetail]:
    """Return the full attestation provenance for a framework.

    Only the framework owner or an admin may read this; it includes rejected
    determinations that are hidden from public surfaces.
    """
    framework = await db.scalar(
        select(Framework).where(Framework.id == framework_id)
    )
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Framework not found."
        )
    is_admin = "admin" in current_user.roles
    if framework.contributor_id != current_user.id and not is_admin:
        logger.bind(
            module="attestation",
            action="framework_provenance_denied",
            user_id=current_user.id,
            framework_id=framework_id,
        ).warning("access_denied")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted."
        )
    return await badge_service.list_framework_provenance(db, framework=framework)
```

Imports to add to `frameworks/router.py`: `from app.modules.attestation import badge_service`, `from app.modules.explore.schemas import AttestationBadgeDetail`, `from loguru import logger`, and confirm `Framework`, `select`, `HTTPException`, `status`, `UUID` are imported. `CurrentUser` / `DatabaseSession` must match the dependency aliases already defined at the top of this router (confirm exact names — the header shows `ContributorUser`, `OperatorUser`, `DatabaseSession`; use the plain authenticated-user dependency the module exposes, e.g. `Annotated[User, Depends(get_current_user)]`; if no such alias exists, define one locally as `CurrentUser = Annotated[User, Depends(get_current_user)]` using the same `get_current_user` the other modules import from `app.core.dependencies`).

Verify `current_user.roles` is the correct attribute for role membership (confirm against `User` model / how `require_role` reads roles). If roles live elsewhere, match `require_role`'s access pattern.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/integration/test_framework_provenance_view.py -v`
Expected: PASS (all three).

- [ ] **Step 6: Lint/type + frameworks regression + commit**

```bash
cd /Users/a0000/projects/auracles/backend && uv run ruff check . && uv run mypy app && uv run pytest tests/integration/test_frameworks_endpoints.py -q
cd /Users/a0000/projects/auracles
git add backend/app/modules/attestation/badge_service.py backend/app/modules/frameworks/router.py backend/tests/integration/test_framework_provenance_view.py
git commit -m "Add owner/admin framework attestation provenance view"
```

---

### Task 7: OpenAPI contract update

**Files:**
- Modify: `contracts/openapi.yaml`
- Test: manual verification (schema export diff)

**Interfaces:**
- Consumes: the three read surfaces (Tasks 4, 5, 6) and their response schemas.
- Produces: `contracts/openapi.yaml` reflecting `attestation_badges` on the framework-detail response, `GET /attestation/attestors/{user_id}/completed`, and `GET /frameworks/{framework_id}/attestation-badges`.

- [ ] **Step 1: Export the live schema and diff**

Run (dumps the FastAPI-generated schema so you can copy the new pieces into the hand-maintained contract):
```
cd /Users/a0000/projects/auracles/backend && uv run python -c "import json, app.main as m; print(json.dumps(m.app.openapi(), indent=2))" > /tmp/openapi_live.json
```
Open `/tmp/openapi_live.json` and locate: the two new paths and the schemas `AttestationBadgeDetail`, `AttestorCompletedAttestation`, and the updated `ExploreFrameworkDetail` (now with `attestation_badges`).

> Note for the implementer: confirm the app import path (`app.main:app`) — check `backend/pyproject.toml`/`uvicorn` entrypoint; adjust the `-c` import if the app object lives elsewhere.

- [ ] **Step 2: Update `contracts/openapi.yaml`**

Add the two new paths and the two new component schemas, and add `attestation_badges` to the `ExploreFrameworkDetail` schema, copying field shapes from the live export. Follow the existing YAML style in the file (path grouping, `components/schemas` ordering, `tags: [Attestation]` / `[Frameworks]`).

- [ ] **Step 3: Validate the contract parses**

Run:
```
cd /Users/a0000/projects/auracles && uv run --project backend python -c "import yaml; yaml.safe_load(open('contracts/openapi.yaml')); print('ok')"
```
Expected: `ok` (valid YAML). If the repo has an OpenAPI lint/validate step in CI, run it too.

- [ ] **Step 4: Commit**

```bash
cd /Users/a0000/projects/auracles
git add contracts/openapi.yaml
git commit -m "Update OpenAPI contract for attestation badge & provenance endpoints"
```

---

## Final verification

- [ ] **Whole-repo lint + type:** `cd /Users/a0000/projects/auracles/backend && uv run ruff check . && uv run mypy app` — clean.
- [ ] **Migration round-trip:** `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` — succeeds.
- [ ] **Full 6c suite:**
```
cd /Users/a0000/projects/auracles/backend && uv run pytest \
  tests/unit/modules/test_attestation_badges_migration.py \
  tests/unit/modules/test_attestation_version_capture.py \
  tests/unit/modules/test_attestation_badge_publish.py \
  tests/integration/test_attestation_badge_publish_wiring.py \
  tests/integration/test_explore_framework_badges.py \
  tests/integration/test_attestor_completed_list.py \
  tests/integration/test_framework_provenance_view.py -v
```
All PASS.
- [ ] **Regression:** `uv run pytest tests/integration/test_attestation_endpoints.py tests/integration/test_explore_endpoints.py tests/integration/test_frameworks_endpoints.py tests/integration/test_attestation_dispute*.py -q` — still green.

## Reviewer notes

- **No escrow, money, or settlement change.** 6c is downstream of close; if a diff touches escrow release amounts or the 90/10 split, that is out of scope — reject.
- **Provenance is insert-only.** No task may add an update/delete path to `attestation_badges`. `publish_badge` is the only writer; it is idempotent via `ON CONFLICT`.
- **Positive-only on public surfaces.** Framework page (Task 4) and attestor completed list (Task 5) must exclude rejected. Only the owner/admin view (Task 6) returns rejected.
- **PII/anti-gaming.** `credentials_snapshot` and every public credential render must expose only the `PublicCredentialResponse` fields — never evidence keys, verification URLs, or reference numbers.
- **RBAC at the dependency/handler layer.** The owner-or-admin check in Task 6 lives in the router; do not push it into `badge_service`.
- **Publish wiring covers exactly the eligible closes:** accept + auto-accept (via `_release_and_close`) and dispute-rejected (report stands). It must NOT fire on `upheld_refund` or admin-refund paths.
- **Version-lock semantics:** `newer_version_exists` is `False` when `framework_version is None`; string inequality (not semver ordering) against `framework.version`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-02-attestation-module-6c-badge-provenance.md`.
