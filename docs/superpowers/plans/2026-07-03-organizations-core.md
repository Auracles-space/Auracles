# Organizations Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the backend Organizations Core module — org entity, owner/admin/member roles, invitations with explicit accept/decline, GitHub-style teams, capability status skeleton, org RBAC dependencies, derived attestor-role sync — as the foundation for org-as-attestor/contributor/operator sub-projects.

**Architecture:** New `app/modules/organizations/` module (standard router/service/models/schemas/dependencies layout) with six tables. Capability *applications* are out of scope: `org_capabilities` ships as a status table with no activation path. RBAC via new `require_org_role` / `require_org_capability` FastAPI dependencies layered on `get_current_user`. Invitations use hashed 32-byte tokens emailed via Resend Celery tasks, with a daily Beat expiry sweep.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, Pydantic v2, PostgreSQL 16, Celery + Redis, Resend, pytest + pytest-asyncio, httpx AsyncClient.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-03-organizations-core-design.md`. Every requirement there binds.
- All backend commands run from `backend/`: `cd /Users/a0000/projects/auracles/backend`.
- Runner is `uv`: `uv run pytest ...`, `uv run alembic ...`, `uv run ruff check .`, `uv run mypy app`.
- Alembic current head is `2026_07_02_0057`. New migration filenames: `2026_07_03_0058_organizations_core.py`, `2026_07_03_0059_org_invitations.py`, `2026_07_03_0060_org_invitation_notification_types.py`, `2026_07_03_0061_org_teams.py`. Each `down_revision` chains to the previous.
- `alembic upgrade head` and `alembic downgrade -1` must both succeed for every migration.
- The spec's `citext` columns are realized as lowercase-normalized `String(255)` (service layer lowercases on write and compare) — matches the existing `users.email` pattern; this codebase does not use the citext extension.
- Org roles: `owner` > `admin` > `member` (hierarchy — owner passes admin checks, admin passes member checks). Exactly one owner per org (partial unique index `uq_org_members_single_owner` + service invariant).
- Invitation expiry: 7 days. Invitation create rate limit: 20 per org per hour (`RateLimiter(namespace="org_invite", limit=20, window=3600)` keyed by org id).
- Invitation tokens: `secrets.token_urlsafe(32)`, stored via existing `app.core.security.hash_token` (SHA-256), raw token only in the email link. Never logged.
- RBAC at dependency layer only, never inside services. Every org RBAC denial audited: `write_audit(db=db, actor_id=..., action="access_denied", target_type="org_rbac", target_id=org_id, metadata=...)` then `await db.commit()` before raising (same as `require_role` in `app/core/dependencies.py:171-197`).
- Audited events (via `app.core.audit.write_audit`): `org_created`, `org_deactivated`, `org_member_invited`, `org_member_joined`, `org_member_removed`, `org_member_role_changed`, `org_ownership_transferred`, `org_team_created`, `org_team_deleted`, `org_capability_status_changed`, `org_suspended`, plus `access_denied`.
- Error mapping: 401 unauthenticated; 403 wrong org role / suspended / invite email mismatch; 404 unknown org/member/team/invitation; 409 duplicate pending invite / duplicate team name / owner-removal / second accept of a used token; 422 Pydantic; 429 invite rate limit.
- Response schemas explicit Pydantic v2 with `model_config = ConfigDict(from_attributes=True)`; never return ORM rows.
- Logging: `loguru`, `logger.bind(module="organizations", action=..., user_id=..., org_id=...)`. No tokens or member emails in logs.
- Docstrings: module-level on every new file; Google-style on every public function/class; test functions get a one-line docstring naming the behavior under test.
- TDD: failing test first, watch it fail, minimal implementation, watch it pass, commit. One behavior per cycle.
- Before claiming any task clean: `uv run ruff check .` and `uv run mypy app` from `backend/` (CI lints tests too).
- Commits on `main`, no branches. Commit messages end at the last meaningful line — no `Co-Authored-By: Claude` trailer.
- Backend-only: no frontend changes except the generated client in Task 13.

## File Structure

```
backend/app/modules/organizations/
├── __init__.py          # empty package marker with module docstring
├── models.py            # 6 ORM tables + enums
├── schemas.py           # Pydantic request/response schemas
├── service.py           # business logic: org CRUD, members, invitations, teams, derived roles
├── router.py            # /v1/orgs + /v1/org-invitations + /v1/admin/orgs routes
└── dependencies.py      # require_org_role, require_org_capability

backend/migrations/versions/2026_07_03_00{58,59,60,61}_*.py
backend/app/workers/tasks/org_notifications.py   # Resend email task
backend/app/workers/tasks/organizations_beat.py  # invitation expiry sweep
backend/app/integrations/resend.py               # + send_org_invitation_email
backend/app/modules/notifications/models.py      # + 3 enum values
backend/app/modules/notifications/preferences.py # + category map entries
backend/app/workers/beat_schedule.py             # + sweep entry
backend/app/main.py                              # + organizations_router
backend/app/modules/gdpr/export_service.py       # + org memberships section
backend/app/modules/gdpr/deletion_service.py     # + sole-owner blocker
backend/tests/unit/modules/test_organizations_service.py
backend/tests/integration/test_organizations_endpoints.py
backend/tests/integration/test_org_invitations_endpoints.py
backend/tests/integration/test_org_teams_endpoints.py
backend/tests/integration/test_org_admin_endpoints.py
contracts/openapi.yaml                            # Task 13
frontend/src/lib/generated/*                      # Task 13 (regenerated)
```

---

### Task 1: Core migration + ORM models (organizations, org_members, org_capabilities)

**Files:**
- Create: `backend/migrations/versions/2026_07_03_0058_organizations_core.py`
- Create: `backend/app/modules/organizations/__init__.py`
- Create: `backend/app/modules/organizations/models.py`
- Test: `backend/tests/unit/modules/test_organizations_migration.py`

**Interfaces:**
- Consumes: `users.id`, `app.core.database.Base`, `app.shared.models.base.CreatedAtMixin/UpdatedAtMixin`.
- Produces ORM classes used by every later task:
  - `Organization` (tablename `organizations`): `id, slug (unique), name, logo_key|None, country, website|None, description|None, created_by, deactivated_at|None, created_at, updated_at`
  - `OrgMember` (tablename `org_members`): `id, org_id, user_id, role, joined_at, created_at`; `UNIQUE(org_id, user_id)`; partial unique index `uq_org_members_single_owner ON org_members(org_id) WHERE role='owner'`
  - `OrgCapability` (tablename `org_capabilities`): `id, org_id, capability, status, activated_at|None, created_at, updated_at`; `UNIQUE(org_id, capability)`
  - Enums: `org_member_role_enum('owner','admin','member')`, `org_capability_enum('attestor','contributor','operator')`, `org_capability_status_enum('pending','active','suspended','revoked')`

- [ ] **Step 1: Write the failing migration test**

Create `backend/tests/unit/modules/test_organizations_migration.py`:

```python
"""Migration coverage for Organizations Core schema (migration 0058).

Verifies the org entity, membership (with single-owner partial unique
index), and capability status tables exist with their key constraints.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.main import app


@pytest.fixture
def migrated_engine() -> Iterator[object]:
    """Upgrade to head and yield a sync engine for inspection."""
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(app.state.settings.sync_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_organizations_tables_exist(migrated_engine) -> None:
    """Migration 0058 creates organizations, org_members, org_capabilities."""
    inspector = inspect(migrated_engine)
    tables = inspector.get_table_names()
    assert "organizations" in tables
    assert "org_members" in tables
    assert "org_capabilities" in tables


def test_org_members_single_owner_index(migrated_engine) -> None:
    """org_members carries the single-owner partial unique index."""
    with migrated_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'org_members' "
                "AND indexname = 'uq_org_members_single_owner'"
            )
        ).first()
    assert row is not None
    assert "WHERE" in row[0] and "owner" in row[0]


def test_organizations_slug_unique(migrated_engine) -> None:
    """organizations.slug is unique."""
    inspector = inspect(migrated_engine)
    uniques = inspector.get_unique_constraints("organizations") + [
        {"column_names": idx["column_names"]}
        for idx in inspector.get_indexes("organizations")
        if idx.get("unique")
    ]
    assert any(u["column_names"] == ["slug"] for u in uniques)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/a0000/projects/auracles/backend && uv run pytest tests/unit/modules/test_organizations_migration.py -v`
Expected: FAIL — `assert "organizations" in tables` (tables missing).

- [ ] **Step 3: Write the ORM models**

Create `backend/app/modules/organizations/__init__.py`:

```python
"""Organizations Core module.

Org entity, membership roles, invitations, teams, and the capability
status skeleton consumed by the org-as-attestor/contributor/operator
sub-projects. See docs/superpowers/specs/2026-07-03-organizations-core-design.md.
"""
```

Create `backend/app/modules/organizations/models.py`:

```python
"""SQLAlchemy models for Organizations Core.

Six tables: organizations, org_members, org_invitations, org_teams,
org_team_members, org_capabilities. Invitations and teams are added by
later migrations in this sub-project; this file grows with them.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin

ORG_MEMBER_ROLE_ENUM = ENUM(
    "owner",
    "admin",
    "member",
    name="org_member_role_enum",
    create_type=False,
)
ORG_CAPABILITY_ENUM = ENUM(
    "attestor",
    "contributor",
    "operator",
    name="org_capability_enum",
    create_type=False,
)
ORG_CAPABILITY_STATUS_ENUM = ENUM(
    "pending",
    "active",
    "suspended",
    "revoked",
    name="org_capability_status_enum",
    create_type=False,
)


class Organization(UpdatedAtMixin, Base):
    """An organization: base entity with no commercial power of its own.

    Commercial abilities (attest, publish, purchase) come from
    org_capabilities rows activated by later sub-projects.
    """

    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    logo_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OrgMember(CreatedAtMixin, Base):
    """Membership of a user in an organization with a fixed role."""

    __tablename__ = "org_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_members_org_user"),
        Index(
            "uq_org_members_single_owner",
            "org_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(ORG_MEMBER_ROLE_ENUM, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrgCapability(UpdatedAtMixin, Base):
    """Per-capability commercial status for an organization.

    Rows are created and activated by capability sub-projects; Org Core
    ships the table and read path only — no activation endpoint exists.
    """

    __tablename__ = "org_capabilities"
    __table_args__ = (
        UniqueConstraint("org_id", "capability", name="uq_org_capabilities_org_cap"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    capability: Mapped[str] = mapped_column(ORG_CAPABILITY_ENUM, nullable=False)
    status: Mapped[str] = mapped_column(ORG_CAPABILITY_STATUS_ENUM, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Note: `suspended_at` on `Organization` backs the platform-admin suspend (Task 11); shipping it in the base migration avoids a later ALTER.

- [ ] **Step 4: Write the migration**

Create `backend/migrations/versions/2026_07_03_0058_organizations_core.py`:

```python
"""Organizations Core: org entity, membership, capability skeleton.

Foundation for the org-based attestation redefine
(docs/superpowers/specs/2026-07-03-organizations-core-design.md):
organizations table, org_members with single-owner partial unique index,
and the org_capabilities status table (no activation path in Org Core).

Revision ID: 2026_07_03_0058
Revises: 2026_07_02_0057
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_03_0058"
down_revision: str | None = "2026_07_02_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORG_MEMBER_ROLE = postgresql.ENUM(
    "owner", "admin", "member", name="org_member_role_enum", create_type=False
)
ORG_CAPABILITY = postgresql.ENUM(
    "attestor", "contributor", "operator", name="org_capability_enum", create_type=False
)
ORG_CAPABILITY_STATUS = postgresql.ENUM(
    "pending", "active", "suspended", "revoked",
    name="org_capability_status_enum", create_type=False,
)


def upgrade() -> None:
    """Create organizations, org_members, org_capabilities."""
    ORG_MEMBER_ROLE.create(op.get_bind(), checkfirst=True)
    ORG_CAPABILITY.create(op.get_bind(), checkfirst=True)
    ORG_CAPABILITY_STATUS.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("logo_key", sa.String(512), nullable=True),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("website", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "org_members",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("role", ORG_MEMBER_ROLE, nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_members_org_user"),
    )
    op.create_index(
        "uq_org_members_single_owner",
        "org_members",
        ["org_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )
    op.create_index("idx_org_members_user", "org_members", ["user_id"])

    op.create_table(
        "org_capabilities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capability", ORG_CAPABILITY, nullable=False),
        sa.Column("status", ORG_CAPABILITY_STATUS, nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("org_id", "capability", name="uq_org_capabilities_org_cap"),
    )


def downgrade() -> None:
    """Drop organizations core tables and enums."""
    op.drop_table("org_capabilities")
    op.drop_index("idx_org_members_user", table_name="org_members")
    op.drop_index("uq_org_members_single_owner", table_name="org_members")
    op.drop_table("org_members")
    op.drop_table("organizations")
    ORG_CAPABILITY_STATUS.drop(op.get_bind(), checkfirst=True)
    ORG_CAPABILITY.drop(op.get_bind(), checkfirst=True)
    ORG_MEMBER_ROLE.drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 5: Run migration round-trip and the test**

Run: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: all three succeed.
Run: `uv run pytest tests/unit/modules/test_organizations_migration.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Lint, type-check, commit**

Run: `uv run ruff check . && uv run mypy app`
Expected: clean.

```bash
git add migrations/versions/2026_07_03_0058_organizations_core.py app/modules/organizations/ tests/unit/modules/test_organizations_migration.py
git commit -m "Add Organizations Core schema: orgs, members, capabilities"
```

---

### Task 2: Create org + list mine (service, schemas, router, registration)

**Files:**
- Create: `backend/app/modules/organizations/schemas.py`
- Create: `backend/app/modules/organizations/service.py`
- Create: `backend/app/modules/organizations/router.py`
- Modify: `backend/app/main.py` (import + `include_router`, alphabetical position after `notifications_router` line ~82)
- Test: `backend/tests/integration/test_organizations_endpoints.py`

**Interfaces:**
- Consumes: Task 1 models; `get_current_user`, `get_db`, `write_audit`.
- Produces:
  - `service.create_organization(db, *, user: User, payload: OrganizationCreateRequest) -> Organization` — creates org + owner member row in one transaction; audits `org_created`.
  - `service.list_my_organizations(db, *, user_id: UUID) -> list[tuple[Organization, str, list[OrgCapability]]]` — (org, my role, capabilities).
  - Schemas: `OrganizationCreateRequest(slug, name, country, website=None, description=None)`, `OrganizationResponse(id, slug, name, logo_key, country, website, description, created_at)`, `MyOrganizationResponse(org: OrganizationResponse, role: str, capabilities: dict[str, str])`, `MyOrganizationsResponse(organizations: list[MyOrganizationResponse])`.
  - Router mounted at `/v1/orgs`, tag `Organizations`.

- [ ] **Step 1: Write failing integration tests**

Create `backend/tests/integration/test_organizations_endpoints.py`:

```python
"""Integration tests for Organizations Core org CRUD endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.shared.models.audit_log import AuditLog


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def clean_orgs() -> None:
    """Remove org rows between tests."""
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(OrgCapability))
        await session.execute(delete(OrgMember))
        await session.execute(delete(Organization))
        await session.execute(delete(AuditLog))
        await session.commit()


async def create_user(prefix: str) -> UUID:
    """Create a verified user with a unique email; return its id."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
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
            return user.id


def auth(token: str) -> dict[str, str]:
    """Build an Authorization header."""
    return {"Authorization": f"Bearer {token}"}


async def test_create_org_seeds_owner_membership(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """POST /v1/orgs creates the org and seeds the creator as owner."""
    user_id = await create_user("org-create")
    token = create_access_token(user_id, [])
    slug = f"acme-{uuid4().hex[:6]}"

    response = await client.post(
        "/v1/orgs",
        json={"slug": slug, "name": "Acme Compliance", "country": "GB"},
        headers=auth(token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == slug
    async with async_session_factory() as session:
        member = await session.scalar(
            OrgMember.__table__.select().where(
                OrgMember.org_id == UUID(body["id"]),
                OrgMember.user_id == user_id,
            )
        )
    assert member is not None and member.role == "owner"


async def test_create_org_duplicate_slug_conflicts(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Reusing a slug returns 409."""
    user_id = await create_user("org-dup")
    token = create_access_token(user_id, [])
    slug = f"dup-{uuid4().hex[:6]}"
    first = await client.post(
        "/v1/orgs",
        json={"slug": slug, "name": "First", "country": "GB"},
        headers=auth(token),
    )
    assert first.status_code == 201

    second = await client.post(
        "/v1/orgs",
        json={"slug": slug.upper(), "name": "Second", "country": "GB"},
        headers=auth(token),
    )

    assert second.status_code == 409


async def test_create_org_requires_auth(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Unauthenticated create returns 401."""
    response = await client.post(
        "/v1/orgs", json={"slug": "nope", "name": "Nope", "country": "GB"}
    )
    assert response.status_code == 401


async def test_list_my_orgs_returns_role_and_capabilities(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """GET /v1/orgs/mine lists my orgs with role and capability statuses."""
    user_id = await create_user("org-mine")
    token = create_access_token(user_id, [])
    created = await client.post(
        "/v1/orgs",
        json={"slug": f"mine-{uuid4().hex[:6]}", "name": "Mine", "country": "NG"},
        headers=auth(token),
    )
    org_id = UUID(created.json()["id"])
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(org_id=org_id, capability="attestor", status="pending")
            )

    response = await client.get("/v1/orgs/mine", headers=auth(token))

    assert response.status_code == 200
    orgs = response.json()["organizations"]
    assert len(orgs) == 1
    assert orgs[0]["role"] == "owner"
    assert orgs[0]["capabilities"] == {"attestor": "pending"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_organizations_endpoints.py -v`
Expected: FAIL — 404s (router not mounted) / import error until files exist.

- [ ] **Step 3: Implement schemas, service, router; register router**

Create `backend/app/modules/organizations/schemas.py`:

```python
"""Pydantic schemas for Organizations Core."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrganizationCreateRequest(BaseModel):
    """Request body to create an organization."""

    slug: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9-]+$")
    name: str = Field(min_length=2, max_length=120)
    country: str = Field(min_length=2, max_length=2)
    website: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("slug", "country")
    @classmethod
    def lowercase(cls, value: str) -> str:
        """Normalize case-insensitive identifiers to lowercase."""
        return value.lower() if len(value) != 2 else value.upper()


class OrganizationResponse(BaseModel):
    """Public-safe organization fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    logo_key: str | None
    country: str
    website: str | None
    description: str | None
    created_at: datetime


class MyOrganizationResponse(BaseModel):
    """An org I belong to, with my role and its capability statuses."""

    org: OrganizationResponse
    role: str
    capabilities: dict[str, str]


class MyOrganizationsResponse(BaseModel):
    """List wrapper for GET /v1/orgs/mine."""

    organizations: list[MyOrganizationResponse]
```

Note on the `lowercase` validator: `country` is exactly 2 chars and must be uppercase ISO 3166-1; `slug` is min 3 chars and lowercased. The shared validator branches on length — if the reviewer finds this too clever, split into two validators.

Create `backend/app/modules/organizations/service.py`:

```python
"""Organizations Core service layer.

Org CRUD, membership, invitations, teams, capability reads, and the
derived attestor-role sync. RBAC lives in dependencies.py, never here.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.auth.models import User
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.modules.organizations.schemas import (
    MyOrganizationResponse,
    MyOrganizationsResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
)


async def create_organization(
    db: AsyncSession,
    *,
    user: User,
    payload: OrganizationCreateRequest,
) -> OrganizationResponse:
    """Create an organization and seed the creator as its owner.

    Args:
        db: Async database session.
        user: Authenticated creator; becomes the single owner.
        payload: Validated org fields (slug already lowercased).

    Returns:
        The created organization.

    Raises:
        HTTPException(409): If the slug is already taken.
    """
    if db.in_transaction():
        await db.rollback()
    try:
        async with db.begin():
            org = Organization(
                slug=payload.slug,
                name=payload.name,
                country=payload.country,
                website=payload.website,
                description=payload.description,
                created_by=user.id,
            )
            db.add(org)
            await db.flush()
            db.add(OrgMember(org_id=org.id, user_id=user.id, role="owner"))
            await write_audit(
                db=db,
                actor_id=user.id,
                action="org_created",
                target_type="organization",
                target_id=org.id,
                metadata={"slug": payload.slug},
            )
            response = OrganizationResponse.model_validate(org)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization slug is already taken.",
        ) from exc
    logger.bind(
        module="organizations", action="org_created", user_id=str(user.id),
        org_id=str(response.id),
    ).info("organization created")
    return response


async def list_my_organizations(
    db: AsyncSession, *, user_id: UUID
) -> MyOrganizationsResponse:
    """List organizations the user belongs to with role and capabilities."""
    rows = (
        await db.execute(
            select(Organization, OrgMember.role)
            .join(OrgMember, OrgMember.org_id == Organization.id)
            .where(
                OrgMember.user_id == user_id,
                Organization.deactivated_at.is_(None),
            )
            .order_by(Organization.created_at)
        )
    ).all()
    org_ids = [org.id for org, _ in rows]
    capabilities: dict[UUID, dict[str, str]] = {org_id: {} for org_id in org_ids}
    if org_ids:
        for cap in (
            await db.scalars(
                select(OrgCapability).where(OrgCapability.org_id.in_(org_ids))
            )
        ).all():
            capabilities[cap.org_id][cap.capability] = cap.status
    return MyOrganizationsResponse(
        organizations=[
            MyOrganizationResponse(
                org=OrganizationResponse.model_validate(org),
                role=role,
                capabilities=capabilities.get(org.id, {}),
            )
            for org, role in rows
        ]
    )
```

Create `backend/app/modules/organizations/router.py`:

```python
"""Organizations API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.organizations import service
from app.modules.organizations.schemas import (
    MyOrganizationsResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
)

router = APIRouter(tags=["Organizations"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "/orgs",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create organization",
    description="Create a base organization; the creator becomes its owner.",
)
async def create_organization(
    payload: OrganizationCreateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrganizationResponse:
    """Create an organization owned by the current user."""
    return await service.create_organization(db=db, user=current_user, payload=payload)


@router.get(
    "/orgs/mine",
    response_model=MyOrganizationsResponse,
    summary="List my organizations",
    description="Organizations the current user belongs to, with role and capability statuses.",
)
async def list_my_organizations(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> MyOrganizationsResponse:
    """List the current user's organizations."""
    return await service.list_my_organizations(db=db, user_id=current_user.id)
```

Modify `backend/app/main.py`: add import `from app.modules.organizations.router import router as organizations_router` (alphabetical among the module imports) and `application.include_router(organizations_router, prefix="/v1")` after the `notifications_router` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_organizations_endpoints.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run mypy app`

```bash
git add app/modules/organizations/ app/main.py tests/integration/test_organizations_endpoints.py
git commit -m "Add org creation and my-orgs listing endpoints"
```

---

### Task 3: Org RBAC dependencies + public profile + update + deactivate

**Files:**
- Create: `backend/app/modules/organizations/dependencies.py`
- Modify: `backend/app/modules/organizations/service.py` (add `get_public_org`, `update_organization`, `deactivate_organization`)
- Modify: `backend/app/modules/organizations/schemas.py` (add `OrganizationUpdateRequest`, `PublicOrganizationResponse`)
- Modify: `backend/app/modules/organizations/router.py` (add 3 routes)
- Test: `backend/tests/integration/test_organizations_endpoints.py` (extend), `backend/tests/unit/modules/test_organizations_service.py` (create)

**Interfaces:**
- Consumes: Task 1 models, Task 2 service/router.
- Produces (used by every later org endpoint):
  - `require_org_role(minimum_role: str) -> Callable` — dependency factory; resolves `org_id` from the path, loads the caller's `OrgMember` row, enforces hierarchy `owner > admin > member`, 403 + audit on failure, 403 `org_suspended` when `organization.suspended_at` set, 404 when org missing/deactivated. Returns an `OrgContext` dataclass: `OrgContext(org: Organization, member: OrgMember, user: User)`.
  - `require_org_capability(capability: str) -> Callable` — org has `OrgCapability(status='active')` for `capability`, else 403 `capability_required`.
  - `service.get_public_org(db, *, slug) -> PublicOrganizationResponse` — active capabilities list + member count, zero PII.
  - `service.update_organization(db, *, context, payload) -> OrganizationResponse`.
  - `service.deactivate_organization(db, *, context) -> None` — 409 if any capability `active`; audits `org_deactivated`.
  - `PublicOrganizationResponse(slug, name, logo_key, country, website, description, active_capabilities: list[str], member_count: int, created_at)`.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/integration/test_organizations_endpoints.py`:

```python
async def create_org(client: AsyncClient, token: str, prefix: str) -> dict:
    """Create an org via the API; return the response body."""
    response = await client.post(
        "/v1/orgs",
        json={"slug": f"{prefix}-{uuid4().hex[:6]}", "name": prefix, "country": "GB"},
        headers=auth(token),
    )
    assert response.status_code == 201
    return response.json()


async def test_public_org_profile_exposes_no_members(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """GET /v1/orgs/{slug} is public and returns no member PII."""
    user_id = await create_user("org-public")
    token = create_access_token(user_id, [])
    org = await create_org(client, token, "pub")

    response = await client.get(f"/v1/orgs/{org['slug']}")

    assert response.status_code == 200
    body = response.json()
    assert body["member_count"] == 1
    assert body["active_capabilities"] == []
    assert "members" not in body and "email" not in str(body)


async def test_update_org_requires_admin(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """PATCH /v1/orgs/{org_id} is admin+; a plain member gets 403."""
    owner_id = await create_user("org-upd-owner")
    member_id = await create_user("org-upd-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "upd")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgMember(org_id=UUID(org["id"]), user_id=member_id, role="member")
            )

    member_token = create_access_token(member_id, [])
    denied = await client.patch(
        f"/v1/orgs/{org['id']}", json={"name": "New"}, headers=auth(member_token)
    )
    allowed = await client.patch(
        f"/v1/orgs/{org['id']}", json={"name": "New"}, headers=auth(owner_token)
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["name"] == "New"


async def test_deactivate_blocked_while_capability_active(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """DELETE /v1/orgs/{org_id} returns 409 while any capability is active."""
    owner_id = await create_user("org-deact")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "deact")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=UUID(org["id"]), capability="attestor", status="active"
                )
            )

    blocked = await client.delete(f"/v1/orgs/{org['id']}", headers=auth(token))

    assert blocked.status_code == 409


async def test_deactivate_owner_only(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """DELETE /v1/orgs/{org_id} requires the owner role; admin gets 403."""
    owner_id = await create_user("org-deact-owner")
    admin_id = await create_user("org-deact-admin")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "downer")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgMember(org_id=UUID(org["id"]), user_id=admin_id, role="admin")
            )

    denied = await client.delete(
        f"/v1/orgs/{org['id']}", headers=auth(create_access_token(admin_id, []))
    )
    allowed = await client.delete(f"/v1/orgs/{org['id']}", headers=auth(owner_token))

    assert denied.status_code == 403
    assert allowed.status_code == 204
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_organizations_endpoints.py -v -k "public or update or deactivate"`
Expected: FAIL (404 route not found).

- [ ] **Step 3: Implement dependencies + service + routes**

Create `backend/app/modules/organizations/dependencies.py`:

```python
"""Org-scoped RBAC dependencies.

Layered after `get_current_user`; role hierarchy is owner > admin >
member. RBAC decisions are made here — never inside service functions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.organizations.models import Organization, OrgCapability, OrgMember

_ROLE_RANK = {"member": 0, "admin": 1, "owner": 2}
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True)
class OrgContext:
    """The resolved org, the caller's membership, and the caller."""

    org: Organization
    member: OrgMember
    user: User


async def _load_org_context(
    db: AsyncSession, org_id: UUID, user: User
) -> tuple[Organization, OrgMember | None]:
    """Load an active org and the caller's membership row (if any)."""
    org = await db.scalar(
        select(Organization).where(
            Organization.id == org_id, Organization.deactivated_at.is_(None)
        )
    )
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )
    member = await db.scalar(
        select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id == user.id
        )
    )
    return org, member


async def _deny(
    db: AsyncSession, user: User, org_id: UUID, metadata: dict[str, object]
) -> None:
    """Audit an org RBAC denial and raise 403."""
    await write_audit(
        db=db,
        actor_id=user.id,
        action="access_denied",
        target_type="org_rbac",
        target_id=org_id,
        metadata=metadata,
    )
    await db.commit()
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error_code": "org_role_required"},
    )


def require_org_role(minimum_role: str) -> Callable[..., object]:
    """Build a dependency enforcing an org role from the `org_id` path param.

    Args:
        minimum_role: Lowest role that passes ('member', 'admin', 'owner').
    """

    async def checker(
        org_id: UUID,
        db: DatabaseSession,
        user: Annotated[User, Depends(get_current_user)],
    ) -> OrgContext:
        """Return the org context when the caller holds the required role."""
        org, member = await _load_org_context(db, org_id, user)
        if member is None:
            await _deny(db, user, org_id, {"required_role": minimum_role})
        assert member is not None  # narrowed by _deny raising
        if org.suspended_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "org_suspended"},
            )
        if _ROLE_RANK[member.role] < _ROLE_RANK[minimum_role]:
            await _deny(
                db,
                user,
                org_id,
                {"required_role": minimum_role, "member_role": member.role},
            )
        return OrgContext(org=org, member=member, user=user)

    return checker


def require_org_capability(capability: str) -> Callable[..., object]:
    """Build a dependency requiring an active org capability.

    Layered after `require_org_role("member")` by consumers; resolves
    `org_id` from the path itself so it can also be used standalone.
    """

    async def checker(
        org_id: UUID,
        db: DatabaseSession,
        user: Annotated[User, Depends(get_current_user)],
    ) -> None:
        """Raise 403 unless the org's capability is active."""
        row = await db.scalar(
            select(OrgCapability).where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == capability,
                OrgCapability.status == "active",
            )
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "capability_required", "capability": capability},
            )

    return checker
```

Add to `backend/app/modules/organizations/schemas.py`:

```python
class OrganizationUpdateRequest(BaseModel):
    """Partial update of org profile fields (admin+)."""

    name: str | None = Field(default=None, min_length=2, max_length=120)
    website: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    logo_key: str | None = Field(default=None, max_length=512)


class PublicOrganizationResponse(BaseModel):
    """Public org profile: no member identities, no PII."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    logo_key: str | None
    country: str
    website: str | None
    description: str | None
    active_capabilities: list[str]
    member_count: int
    created_at: datetime
```

Add to `backend/app/modules/organizations/service.py`:

```python
async def get_public_org(db: AsyncSession, *, slug: str) -> PublicOrganizationResponse:
    """Return the public profile for an active org by slug.

    Raises:
        HTTPException(404): If the org is unknown, deactivated, or suspended.
    """
    org = await db.scalar(
        select(Organization).where(
            func.lower(Organization.slug) == slug.lower(),
            Organization.deactivated_at.is_(None),
            Organization.suspended_at.is_(None),
        )
    )
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found."
        )
    member_count = (
        await db.scalar(
            select(func.count()).select_from(OrgMember).where(OrgMember.org_id == org.id)
        )
    ) or 0
    active = (
        await db.scalars(
            select(OrgCapability.capability).where(
                OrgCapability.org_id == org.id, OrgCapability.status == "active"
            )
        )
    ).all()
    return PublicOrganizationResponse(
        slug=org.slug,
        name=org.name,
        logo_key=org.logo_key,
        country=org.country,
        website=org.website,
        description=org.description,
        active_capabilities=sorted(active),
        member_count=member_count,
        created_at=org.created_at,
    )


async def update_organization(
    db: AsyncSession,
    *,
    context: OrgContext,
    payload: OrganizationUpdateRequest,
) -> OrganizationResponse:
    """Apply a partial profile update (admin+ enforced by dependency)."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        org = await db.scalar(
            select(Organization).where(Organization.id == context.org.id)
        )
        assert org is not None
        for field in ("name", "website", "description", "logo_key"):
            value = getattr(payload, field)
            if value is not None:
                setattr(org, field, value)
        response = OrganizationResponse.model_validate(org)
    return response


async def deactivate_organization(db: AsyncSession, *, context: OrgContext) -> None:
    """Soft-delete an org (owner only; blocked while any capability active).

    Raises:
        HTTPException(409): If any capability status is 'active'.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        active = await db.scalar(
            select(func.count())
            .select_from(OrgCapability)
            .where(
                OrgCapability.org_id == context.org.id,
                OrgCapability.status == "active",
            )
        )
        if active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Wind down active capabilities before deactivating the organization.",
            )
        org = await db.scalar(
            select(Organization).where(Organization.id == context.org.id)
        )
        assert org is not None
        org.deactivated_at = datetime.now(UTC)
        await write_audit(
            db=db,
            actor_id=context.user.id,
            action="org_deactivated",
            target_type="organization",
            target_id=org.id,
        )
```

(Extend the service imports: `from datetime import UTC, datetime`, `from sqlalchemy import func, select`, `from app.modules.organizations.dependencies import OrgContext`, plus the new schema names.)

Add to `backend/app/modules/organizations/router.py`:

```python
from app.modules.organizations.dependencies import OrgContext, require_org_role
from app.modules.organizations.schemas import (
    OrganizationUpdateRequest,
    PublicOrganizationResponse,
)

OrgAdmin = Annotated[OrgContext, Depends(require_org_role("admin"))]
OrgOwner = Annotated[OrgContext, Depends(require_org_role("owner"))]
OrgMemberCtx = Annotated[OrgContext, Depends(require_org_role("member"))]


@router.get(
    "/orgs/{slug}",
    response_model=PublicOrganizationResponse,
    summary="Public organization profile",
)
async def get_public_org(slug: str, db: DatabaseSession) -> PublicOrganizationResponse:
    """Return the PII-free public profile of an organization."""
    return await service.get_public_org(db=db, slug=slug)


@router.patch("/orgs/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: UUID,
    payload: OrganizationUpdateRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrganizationResponse:
    """Update org profile fields (admin+)."""
    return await service.update_organization(db=db, context=context, payload=payload)


@router.delete("/orgs/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_organization(
    org_id: UUID,
    context: OrgOwner,
    db: DatabaseSession,
) -> None:
    """Deactivate an organization (owner only)."""
    await service.deactivate_organization(db=db, context=context)
```

**Route-ordering constraint:** `/orgs/mine` must be declared before `/orgs/{slug}` in the router file (FastAPI matches in declaration order; `mine` would otherwise be captured as a slug). `/orgs/{org_id}` (PATCH/DELETE) and `/orgs/{slug}` (GET) share a path shape — the GET route must be declared last of the two and the slug pattern excludes UUIDs naturally only by lookup failure, which is acceptable: a GET of an org_id returns 404 unless a slug matches.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/integration/test_organizations_endpoints.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Lint, type-check, commit**

Run: `uv run ruff check . && uv run mypy app`

```bash
git add app/modules/organizations/ tests/integration/test_organizations_endpoints.py
git commit -m "Add org RBAC dependencies, public profile, update, deactivate"
```

---

### Task 4: Member management (list, remove/leave, role change)

**Files:**
- Modify: `backend/app/modules/organizations/service.py` (add `list_members`, `remove_member`, `change_member_role`)
- Modify: `backend/app/modules/organizations/schemas.py` (add `OrgMemberResponse`, `OrgMembersResponse`, `OrgMemberRoleUpdateRequest`)
- Modify: `backend/app/modules/organizations/router.py` (3 routes)
- Test: `backend/tests/integration/test_organizations_endpoints.py` (extend)

**Interfaces:**
- Consumes: `OrgContext`, `require_org_role`.
- Produces:
  - `service.list_members(db, *, context) -> OrgMembersResponse` — emails included only when caller is admin+.
  - `service.remove_member(db, *, context, member_id: UUID) -> None` — rules: owner unremovable (409); admin cannot remove admin (403) but owner can; self-removal allowed for any non-owner (leave); audits `org_member_removed`.
  - `service.change_member_role(db, *, context, member_id, new_role) -> OrgMemberResponse` — owner only (dependency), member↔admin only (422 on 'owner'); audits `org_member_role_changed`.
  - `OrgMemberResponse(id, user_id, display_name, email: str | None, role, joined_at)`.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/integration/test_organizations_endpoints.py`:

```python
async def add_member(org_id: str, user_id: UUID, role: str) -> UUID:
    """Insert a membership row directly; return the member row id."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=UUID(org_id), user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            return member.id


async def test_member_list_hides_emails_from_plain_members(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """GET members shows emails to admin+ only."""
    owner_id = await create_user("mem-owner")
    member_id = await create_user("mem-plain")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "mem")
    await add_member(org["id"], member_id, "member")

    as_owner = await client.get(
        f"/v1/orgs/{org['id']}/members", headers=auth(owner_token)
    )
    as_member = await client.get(
        f"/v1/orgs/{org['id']}/members",
        headers=auth(create_access_token(member_id, [])),
    )

    assert as_owner.status_code == 200 and as_member.status_code == 200
    assert all(m["email"] for m in as_owner.json()["members"])
    assert all(m["email"] is None for m in as_member.json()["members"])


async def test_owner_cannot_be_removed(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Removing the owner returns 409."""
    owner_id = await create_user("rm-owner")
    admin_id = await create_user("rm-admin")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "rmo")
    await add_member(org["id"], admin_id, "admin")
    async with async_session_factory() as session:
        owner_member = await session.scalar(
            select(OrgMember).where(
                OrgMember.org_id == UUID(org["id"]), OrgMember.role == "owner"
            )
        )

    response = await client.delete(
        f"/v1/orgs/{org['id']}/members/{owner_member.id}",
        headers=auth(create_access_token(admin_id, [])),
    )

    assert response.status_code == 409


async def test_admin_cannot_remove_admin_but_owner_can(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Admin removing another admin → 403; owner removing an admin → 204."""
    owner_id = await create_user("rm2-owner")
    admin_a = await create_user("rm2-admin-a")
    admin_b = await create_user("rm2-admin-b")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "rm2")
    await add_member(org["id"], admin_a, "admin")
    target = await add_member(org["id"], admin_b, "admin")

    denied = await client.delete(
        f"/v1/orgs/{org['id']}/members/{target}",
        headers=auth(create_access_token(admin_a, [])),
    )
    allowed = await client.delete(
        f"/v1/orgs/{org['id']}/members/{target}", headers=auth(owner_token)
    )

    assert denied.status_code == 403
    assert allowed.status_code == 204


async def test_member_can_leave(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Self-removal (leave) is allowed for a non-owner member."""
    owner_id = await create_user("leave-owner")
    member_id = await create_user("leave-member")
    org = await create_org(client, create_access_token(owner_id, []), "leave")
    member_row = await add_member(org["id"], member_id, "member")

    response = await client.delete(
        f"/v1/orgs/{org['id']}/members/{member_row}",
        headers=auth(create_access_token(member_id, [])),
    )

    assert response.status_code == 204


async def test_role_change_owner_only_and_never_to_owner(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """PATCH member role: owner promotes member→admin; 'owner' rejected 422."""
    owner_id = await create_user("role-owner")
    member_id = await create_user("role-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "role")
    member_row = await add_member(org["id"], member_id, "member")

    promoted = await client.patch(
        f"/v1/orgs/{org['id']}/members/{member_row}",
        json={"role": "admin"},
        headers=auth(owner_token),
    )
    to_owner = await client.patch(
        f"/v1/orgs/{org['id']}/members/{member_row}",
        json={"role": "owner"},
        headers=auth(owner_token),
    )

    assert promoted.status_code == 200 and promoted.json()["role"] == "admin"
    assert to_owner.status_code == 422
```

Add `from sqlalchemy import select` to the test file imports.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_organizations_endpoints.py -v -k "member or remove or leave or role_change"`
Expected: FAIL (404).

- [ ] **Step 3: Implement**

Add to `backend/app/modules/organizations/schemas.py`:

```python
from typing import Literal


class OrgMemberResponse(BaseModel):
    """A member row; email present only for admin+ callers."""

    id: UUID
    user_id: UUID
    display_name: str
    email: str | None
    role: str
    joined_at: datetime


class OrgMembersResponse(BaseModel):
    """List wrapper for org members."""

    members: list[OrgMemberResponse]


class OrgMemberRoleUpdateRequest(BaseModel):
    """Role change request; owner assignment goes through transfer-ownership."""

    role: Literal["admin", "member"]
```

Add to `backend/app/modules/organizations/service.py`:

```python
async def list_members(db: AsyncSession, *, context: OrgContext) -> OrgMembersResponse:
    """List org members; emails included only for admin+ callers."""
    include_email = context.member.role in ("owner", "admin")
    rows = (
        await db.execute(
            select(OrgMember, User.display_name, User.email)
            .join(User, User.id == OrgMember.user_id)
            .where(OrgMember.org_id == context.org.id)
            .order_by(OrgMember.joined_at)
        )
    ).all()
    return OrgMembersResponse(
        members=[
            OrgMemberResponse(
                id=member.id,
                user_id=member.user_id,
                display_name=display_name,
                email=email if include_email else None,
                role=member.role,
                joined_at=member.joined_at,
            )
            for member, display_name, email in rows
        ]
    )


async def _get_member_row(
    db: AsyncSession, org_id: UUID, member_id: UUID
) -> OrgMember:
    """Load a member row in this org or raise 404."""
    member = await db.scalar(
        select(OrgMember).where(OrgMember.id == member_id, OrgMember.org_id == org_id)
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found."
        )
    return member


async def remove_member(
    db: AsyncSession, *, context: OrgContext, member_id: UUID
) -> None:
    """Remove a member (or leave, when removing self).

    Rules: the owner can never be removed (409); an admin cannot remove
    another admin (403) though the owner can; any non-owner may remove
    themself (leave). Plain members may only remove themself.

    Raises:
        HTTPException(403): Caller lacks the right to remove this member.
        HTTPException(404): Member not in this org.
        HTTPException(409): Target is the owner.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        target = await _get_member_row(db, context.org.id, member_id)
        if target.role == "owner":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Transfer ownership before removing the owner.",
            )
        is_self = target.user_id == context.user.id
        caller_role = context.member.role
        if not is_self:
            if caller_role == "member":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
            if caller_role == "admin" and target.role == "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the owner can remove an admin.",
                )
        removed_user_id = target.user_id
        await db.delete(target)
        await write_audit(
            db=db,
            actor_id=context.user.id,
            action="org_member_removed",
            target_type="organization",
            target_id=context.org.id,
            metadata={"removed_user_id": str(removed_user_id), "self": is_self},
        )
    await sync_derived_roles(db, user_id=removed_user_id)


async def change_member_role(
    db: AsyncSession,
    *,
    context: OrgContext,
    member_id: UUID,
    new_role: str,
) -> OrgMemberResponse:
    """Change a member's role between 'member' and 'admin' (owner only)."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        target = await _get_member_row(db, context.org.id, member_id)
        if target.role == "owner":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Use transfer-ownership to change the owner.",
            )
        old_role = target.role
        target.role = new_role
        await write_audit(
            db=db,
            actor_id=context.user.id,
            action="org_member_role_changed",
            target_type="organization",
            target_id=context.org.id,
            metadata={"member_user_id": str(target.user_id), "from": old_role, "to": new_role},
        )
        user = await db.scalar(select(User).where(User.id == target.user_id))
        assert user is not None
        return OrgMemberResponse(
            id=target.id,
            user_id=target.user_id,
            display_name=user.display_name,
            email=user.email,
            role=target.role,
            joined_at=target.joined_at,
        )
```

`sync_derived_roles` does not exist until Task 10. To keep this task self-contained, add the inert placeholder-free version now in `service.py` (Task 10 completes it):

```python
async def sync_derived_roles(db: AsyncSession, *, user_id: UUID) -> None:
    """Grant/revoke the derived user-level attestor role for this user.

    Completed in the derived-roles task; safe to call from member paths
    from day one. With no active attestor capabilities in Org Core it is
    a no-op revoke path.
    """
    # Full grant/revoke logic lands with the derived-roles task; the call
    # sites (member add/remove, capability change) are wired here first.
    return None
```

Add routes to `router.py` — the remove route uses `member+` (self-leave) with the fine-grained rules in the service:

```python
from app.modules.organizations.schemas import (
    OrgMemberResponse,
    OrgMemberRoleUpdateRequest,
    OrgMembersResponse,
)


@router.get("/orgs/{org_id}/members", response_model=OrgMembersResponse)
async def list_members(
    org_id: UUID, context: OrgMemberCtx, db: DatabaseSession
) -> OrgMembersResponse:
    """List members; emails visible to admin+ only."""
    return await service.list_members(db=db, context=context)


@router.delete(
    "/orgs/{org_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    org_id: UUID, member_id: UUID, context: OrgMemberCtx, db: DatabaseSession
) -> None:
    """Remove a member, or leave the org when removing yourself."""
    await service.remove_member(db=db, context=context, member_id=member_id)


@router.patch("/orgs/{org_id}/members/{member_id}", response_model=OrgMemberResponse)
async def change_member_role(
    org_id: UUID,
    member_id: UUID,
    payload: OrgMemberRoleUpdateRequest,
    context: OrgOwner,
    db: DatabaseSession,
) -> OrgMemberResponse:
    """Change a member's role between member and admin (owner only)."""
    return await service.change_member_role(
        db=db, context=context, member_id=member_id, new_role=payload.role
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_organizations_endpoints.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy app
git add app/modules/organizations/ tests/integration/test_organizations_endpoints.py
git commit -m "Add org member list, removal rules, and role changes"
```

---

### Task 5: Ownership transfer (TOTP-gated)

**Files:**
- Modify: `backend/app/modules/organizations/service.py` (add `transfer_ownership`)
- Modify: `backend/app/modules/organizations/schemas.py` (add `OrgOwnershipTransferRequest`)
- Modify: `backend/app/modules/organizations/router.py` (1 route, needs `get_redis`)
- Test: `backend/tests/integration/test_organizations_endpoints.py` (extend)

**Interfaces:**
- Consumes: `app.modules.auth.service.verify_totp_for_sensitive_action(db, redis, user, code)` (raises 403 when TOTP disabled; verifies TOTP or backup code otherwise).
- Produces: `service.transfer_ownership(db, redis, *, context, new_owner_member_id, totp_code) -> None` — old owner becomes `admin`, target becomes `owner`, single transaction, audits `org_ownership_transferred`.
- `OrgOwnershipTransferRequest(new_owner_member_id: UUID, totp_code: str)`.

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/integration/test_organizations_endpoints.py`:

```python
async def test_ownership_transfer_requires_totp(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Transfer without TOTP enabled returns 403 (2FA gate)."""
    owner_id = await create_user("xfer-owner")
    member_id = await create_user("xfer-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "xfer")
    member_row = await add_member(org["id"], member_id, "member")

    response = await client.post(
        f"/v1/orgs/{org['id']}/transfer-ownership",
        json={"new_owner_member_id": str(member_row), "totp_code": "000000"},
        headers=auth(owner_token),
    )

    assert response.status_code == 403


async def test_ownership_transfer_swaps_roles(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verified transfer makes the target owner and the old owner admin."""
    from app.modules.organizations import service as org_service

    async def totp_ok(db, redis, user, code) -> None:  # noqa: ANN001
        return None

    monkeypatch.setattr(org_service, "verify_totp_for_sensitive_action", totp_ok)
    owner_id = await create_user("xfer2-owner")
    member_id = await create_user("xfer2-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "xfer2")
    member_row = await add_member(org["id"], member_id, "admin")

    response = await client.post(
        f"/v1/orgs/{org['id']}/transfer-ownership",
        json={"new_owner_member_id": str(member_row), "totp_code": "123456"},
        headers=auth(owner_token),
    )

    assert response.status_code == 204
    async with async_session_factory() as session:
        roles = {
            m.user_id: m.role
            for m in (
                await session.scalars(
                    select(OrgMember).where(OrgMember.org_id == UUID(org["id"]))
                )
            ).all()
        }
    assert roles[member_id] == "owner"
    assert roles[owner_id] == "admin"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_organizations_endpoints.py -v -k transfer`
Expected: FAIL (404).

- [ ] **Step 3: Implement**

Schema:

```python
class OrgOwnershipTransferRequest(BaseModel):
    """TOTP-gated ownership transfer to an existing member."""

    new_owner_member_id: UUID
    totp_code: str = Field(min_length=6, max_length=16)
```

Service (import `from redis.asyncio import Redis` and `from app.modules.auth.service import verify_totp_for_sensitive_action`):

```python
async def transfer_ownership(
    db: AsyncSession,
    redis: Redis,
    *,
    context: OrgContext,
    new_owner_member_id: UUID,
    totp_code: str,
) -> None:
    """Transfer org ownership to another member (owner only, TOTP-gated).

    The single-owner partial unique index makes the swap order matter:
    demote the current owner first, then promote the target, inside one
    transaction.

    Raises:
        HTTPException(403): TOTP missing/invalid or TOTP not enabled.
        HTTPException(404): Target member not in this org.
        HTTPException(409): Target is already the owner.
    """
    await verify_totp_for_sensitive_action(db, redis, context.user, totp_code)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        target = await _get_member_row(db, context.org.id, new_owner_member_id)
        if target.id == context.member.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already own this organization.",
            )
        current_owner = await db.scalar(
            select(OrgMember)
            .where(OrgMember.org_id == context.org.id, OrgMember.role == "owner")
            .with_for_update()
        )
        assert current_owner is not None
        current_owner.role = "admin"
        await db.flush()
        target.role = "owner"
        await write_audit(
            db=db,
            actor_id=context.user.id,
            action="org_ownership_transferred",
            target_type="organization",
            target_id=context.org.id,
            metadata={"new_owner_user_id": str(target.user_id)},
        )
```

Router (add `RedisClient = Annotated[Redis, Depends(get_redis)]` with `from redis.asyncio import Redis` and `from app.core.redis import get_redis`):

```python
@router.post(
    "/orgs/{org_id}/transfer-ownership", status_code=status.HTTP_204_NO_CONTENT
)
async def transfer_ownership(
    org_id: UUID,
    payload: OrgOwnershipTransferRequest,
    context: OrgOwner,
    db: DatabaseSession,
    redis: RedisClient,
) -> None:
    """Transfer ownership to another member after TOTP verification."""
    await service.transfer_ownership(
        db=db,
        redis=redis,
        context=context,
        new_owner_member_id=payload.new_owner_member_id,
        totp_code=payload.totp_code,
    )
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/integration/test_organizations_endpoints.py -v
uv run ruff check . && uv run mypy app
git add app/modules/organizations/ tests/integration/test_organizations_endpoints.py
git commit -m "Add TOTP-gated org ownership transfer"
```

---

### Task 6: Invitations — create/list/revoke, rate limit, email + in-app notification

**Files:**
- Create: `backend/migrations/versions/2026_07_03_0059_org_invitations.py`
- Create: `backend/migrations/versions/2026_07_03_0060_org_invitation_notification_types.py`
- Create: `backend/app/workers/tasks/org_notifications.py`
- Modify: `backend/app/modules/organizations/models.py` (add `OrgInvitation`)
- Modify: `backend/app/modules/organizations/{schemas,service,router}.py`
- Modify: `backend/app/integrations/resend.py` (add `send_org_invitation_email`)
- Modify: `backend/app/modules/notifications/models.py` (3 new enum values in `NOTIFICATION_TYPE_ENUM`)
- Modify: `backend/app/modules/notifications/preferences.py` (map the 3 types to category `account`)
- Test: `backend/tests/integration/test_org_invitations_endpoints.py`

**Interfaces:**
- Produces:
  - `OrgInvitation` model: `id, org_id, email (lowercased String(255)), role ('admin'|'member' via org_member_role_enum values constrained in service), invited_by, status org_invitation_status_enum('pending','accepted','declined','revoked','expired'), token_hash, expires_at, responded_at|None, created_at`; partial unique index `uq_org_invitations_pending ON (org_id, email) WHERE status='pending'`.
  - `service.create_invitation(db, redis, *, context, payload) -> OrgInvitationResponse` — lowercases email, 409 on duplicate pending, 409 if already a member, rate-limited `RateLimiter("org_invite", 20, 3600)` keyed `str(org.id)`, generates `secrets.token_urlsafe(32)`, stores `hash_token(raw)`, dispatches `send_org_invitation.delay(email, org_name, role, raw_token)`, in-app notification (`org_invitation_received`) when the email matches an existing user, audits `org_member_invited`.
  - `service.list_invitations(db, *, context) -> OrgInvitationsResponse` (pending only).
  - `service.revoke_invitation(db, *, context, invitation_id) -> None` (pending → revoked, else 409).
  - Celery task `send_org_invitation(email, org_name, role, token)` in `org_notifications.py` (`bind=True, max_retries=5, rate_limit="2/s"`, retry on transient `EmailError`, same shape as `app/workers/tasks/notifications.py` tasks).
  - `send_org_invitation_email(email, org_name, role, token)` in `resend.py` — accept link `{FRONTEND_BASE_URL}/org-invitations/{token}`; follow the file's existing template/builder pattern (subject: `You're invited to join {org_name} on Auracles`).
  - Notification enum values: `org_invitation_received`, `org_invitation_accepted`, `org_invitation_declined` (migration 0060 `ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS`, autocommit block, no-op downgrade — copy the 0057 pattern), mapped to category `account` in `preferences.py`, appended to `NOTIFICATION_TYPE_ENUM` in `notifications/models.py`.

Migration 0059 mirrors 0058's structure: create `org_invitation_status_enum`, the table, the partial unique index `uq_org_invitations_pending` (`postgresql_where=sa.text("status = 'pending'")`), and index `idx_org_invitations_email`. Downgrade drops table + enum.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/integration/test_org_invitations_endpoints.py` (reuse the fixture/helper pattern from `test_organizations_endpoints.py`: `migrated_database`, `clean_orgs` extended to also delete `OrgInvitation` and `Notification` rows, `create_user`, `create_org`, `add_member`, `auth`; override `get_redis` with the `FakeRedis` incr/expire/ttl double from `tests/integration/test_query_token_auth_scope.py` so rate limits pass by default):

```python
async def test_invite_creates_pending_and_dispatches_email(
    client: AsyncClient, migrated_database: None, clean_invites: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST invitations stores a hashed-token pending invite and emails it."""
    sent: list[tuple[str, str]] = []

    def fake_delay(email: str, org_name: str, role: str, token: str) -> None:
        sent.append((email, token))

    from app.workers.tasks import org_notifications

    monkeypatch.setattr(org_notifications.send_org_invitation, "delay", fake_delay)
    owner_id = await create_user("inv-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "inv")

    response = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "Invitee@Auracles.SPACE", "role": "member"},
        headers=auth(token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "invitee@auracles.space"
    assert body["status"] == "pending"
    assert len(sent) == 1
    raw_token = sent[0][1]
    async with async_session_factory() as session:
        invite = await session.scalar(select(OrgInvitation))
    assert invite.token_hash == hash_token(raw_token)
    assert invite.token_hash != raw_token


async def test_duplicate_pending_invite_conflicts(
    client: AsyncClient, migrated_database: None, clean_invites: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second pending invite for the same email in the same org → 409."""
    _mute_email(monkeypatch)
    owner_id = await create_user("inv-dup")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "invdup")
    first = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "dup@auracles.space", "role": "member"},
        headers=auth(token),
    )
    assert first.status_code == 201

    second = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "dup@auracles.space", "role": "member"},
        headers=auth(token),
    )

    assert second.status_code == 409


async def test_invite_admin_plus_only(
    client: AsyncClient, migrated_database: None, clean_invites: None,
) -> None:
    """Plain members cannot invite (403)."""
    owner_id = await create_user("inv-rbac-owner")
    member_id = await create_user("inv-rbac-member")
    org = await create_org(client, create_access_token(owner_id, []), "invrbac")
    await add_member(org["id"], member_id, "member")

    response = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "x@auracles.space", "role": "member"},
        headers=auth(create_access_token(member_id, [])),
    )

    assert response.status_code == 403


async def test_revoke_pending_invite(
    client: AsyncClient, migrated_database: None, clean_invites: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE a pending invitation marks it revoked; revoking again → 409."""
    _mute_email(monkeypatch)
    owner_id = await create_user("inv-rev")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "invrev")
    created = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "rev@auracles.space", "role": "member"},
        headers=auth(token),
    )
    invitation_id = created.json()["id"]

    first = await client.delete(
        f"/v1/orgs/{org['id']}/invitations/{invitation_id}", headers=auth(token)
    )
    second = await client.delete(
        f"/v1/orgs/{org['id']}/invitations/{invitation_id}", headers=auth(token)
    )

    assert first.status_code == 204
    assert second.status_code == 409
```

`_mute_email` is a 3-line helper in the test file that monkeypatches `send_org_invitation.delay` to a no-op. Include a rate-limit test: monkeypatch FakeRedis `incr` to return 21 → expect 429.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/integration/test_org_invitations_endpoints.py -v`; expected: import errors/404.

- [ ] **Step 3: Implement** — model, both migrations, schemas (`OrgInvitationCreateRequest(email: EmailStr, role: Literal["admin","member"])`, `OrgInvitationResponse(id, email, role, status, expires_at, created_at)`, `OrgInvitationsResponse`), service functions per the Interfaces block, Resend sender, Celery task, router routes (`POST`/`GET`/`DELETE` under `/orgs/{org_id}/invitations`, all `OrgAdmin`). Service create flow:

```python
INVITATION_TTL_DAYS = 7
_invite_rate_limiter = RateLimiter(namespace="org_invite", limit=20, window=3600)


async def create_invitation(
    db: AsyncSession,
    redis: Redis,
    *,
    context: OrgContext,
    payload: OrgInvitationCreateRequest,
) -> OrgInvitationResponse:
    """Invite a user by email to join the org (admin+, rate-limited).

    Raises:
        HTTPException(409): Duplicate pending invite or already a member.
        HTTPException(429): Org exceeded 20 invitations this hour.
    """
    await _invite_rate_limiter.check(redis, str(context.org.id))
    email = payload.email.lower()
    if db.in_transaction():
        await db.rollback()
    raw_token = secrets.token_urlsafe(32)
    try:
        async with db.begin():
            existing_member = await db.scalar(
                select(OrgMember)
                .join(User, User.id == OrgMember.user_id)
                .where(
                    OrgMember.org_id == context.org.id,
                    func.lower(User.email) == email,
                )
            )
            if existing_member is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This user is already a member.",
                )
            invitation = OrgInvitation(
                org_id=context.org.id,
                email=email,
                role=payload.role,
                invited_by=context.user.id,
                status="pending",
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(days=INVITATION_TTL_DAYS),
            )
            db.add(invitation)
            await db.flush()
            await write_audit(
                db=db,
                actor_id=context.user.id,
                action="org_member_invited",
                target_type="organization",
                target_id=context.org.id,
                metadata={"role": payload.role},
            )
            invitee = await db.scalar(
                select(User).where(func.lower(User.email) == email)
            )
            if invitee is not None:
                await create_notification(
                    db=db,
                    user_id=invitee.id,
                    notification_type="org_invitation_received",
                    title=f"Invitation to join {context.org.name}",
                    body=f"You've been invited to join {context.org.name} as {payload.role}.",
                    link="/settings/organizations",
                    payload={"org_id": str(context.org.id)},
                    dedupe_key=f"org-invite-{invitation.id}",
                )
            response = OrgInvitationResponse.model_validate(invitation)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending invitation for this email already exists.",
        ) from exc
    send_org_invitation.delay(email, context.org.name, payload.role, raw_token)
    return response
```

(Audit metadata deliberately omits the invitee email — PII-minimal. Email dispatch happens after commit so a failed transaction never emails.) Celery task in `org_notifications.py`:

```python
"""Celery tasks for organization emails."""

from loguru import logger

from app.integrations.resend import EmailError, PermanentEmailError
from app.integrations.resend import send_org_invitation_email
from app.workers.celery_app import app


@app.task(bind=True, max_retries=5, rate_limit="2/s")  # type: ignore[untyped-decorator]
def send_org_invitation(self, email: str, org_name: str, role: str, token: str) -> None:
    """Send an org invitation email with the accept link."""
    log = logger.bind(
        module="organizations", action="send_org_invitation", task_id=self.request.id
    )
    try:
        send_org_invitation_email(email=email, org_name=org_name, role=role, token=token)
        log.info("task_completed")
    except PermanentEmailError:
        log.error("task_failed_permanent")
        raise
    except EmailError as exc:
        log.warning("task_retrying")
        raise self.retry(exc=exc, countdown=60) from exc
```

(Check the exact exception names exported by `app/integrations/resend.py` — `PermanentEmailError` is confirmed; use whatever transient base the existing tasks in `app/workers/tasks/notifications.py` catch.)

- [ ] **Step 4: Migration round-trip + tests** — `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` (repeat check for 0060), then `uv run pytest tests/integration/test_org_invitations_endpoints.py -v` → PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy app
git add migrations/versions/2026_07_03_0059_org_invitations.py migrations/versions/2026_07_03_0060_org_invitation_notification_types.py app/modules/organizations/ app/workers/tasks/org_notifications.py app/integrations/resend.py app/modules/notifications/ tests/integration/test_org_invitations_endpoints.py
git commit -m "Add org invitations: create, list, revoke, email + notification"
```

---

### Task 7: Invitations — preview, accept, decline

**Files:**
- Modify: `backend/app/modules/organizations/{schemas,service,router}.py`
- Test: `backend/tests/integration/test_org_invitations_endpoints.py` (extend)

**Interfaces:**
- Produces:
  - `GET /v1/org-invitations/{token}` (authed) → `OrgInvitationPreviewResponse(org_name, org_slug, role, expires_at)`; 404 unknown/expired/terminal token.
  - `POST /v1/org-invitations/{token}/accept` (authed) → 200 `MyOrganizationResponse`; requires `current_user.email.lower() == invitation.email` else 403; expired → 410; terminal status → 409; creates `OrgMember` + flips status inside one transaction; audits `org_member_joined`; notifies inviter (`org_invitation_accepted`); calls `sync_derived_roles(db, user_id=...)` after commit.
  - `POST /v1/org-invitations/{token}/decline` (authed, same email match) → 204; notifies inviter (`org_invitation_declined`).
  - Lookup is by `hash_token(token)`; a token for a suspended/deactivated org → 404.

- [ ] **Step 1: Write failing tests**

Append (full code) tests:

```python
async def invite(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, org: dict, token: str,
    email: str, role: str = "member",
) -> str:
    """Create an invitation and return the raw emailed token."""
    captured: list[str] = []

    from app.workers.tasks import org_notifications

    monkeypatch.setattr(
        org_notifications.send_org_invitation,
        "delay",
        lambda _e, _o, _r, t: captured.append(t),
    )
    response = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": email, "role": role},
        headers=auth(token),
    )
    assert response.status_code == 201
    return captured[0]


async def test_accept_requires_matching_email(
    client: AsyncClient, migrated_database: None, clean_invites: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepting with a different account email returns 403."""
    owner_id = await create_user("acc-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "accmm")
    raw = await invite(client, monkeypatch, org, owner_token, "target@auracles.space")
    other_id = await create_user("acc-other")

    response = await client.post(
        f"/v1/org-invitations/{raw}/accept",
        headers=auth(create_access_token(other_id, [])),
    )

    assert response.status_code == 403


async def test_accept_creates_membership_once(
    client: AsyncClient, migrated_database: None, clean_invites: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept joins the org; a second accept of the same token → 409."""
    owner_id = await create_user("acc2-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "acc2")
    invitee_email = f"acc2-invitee-{uuid4().hex[:8]}@auracles.space"
    raw = await invite(client, monkeypatch, org, owner_token, invitee_email)
    async with async_session_factory() as session:
        async with session.begin():
            invitee = User(
                email=invitee_email,
                password_hash=hash_password("CorrectHorse9"),
                display_name="invitee",
                email_verified=True,
            )
            session.add(invitee)
            await session.flush()
            invitee_id = invitee.id
    invitee_token = create_access_token(invitee_id, [])

    first = await client.post(
        f"/v1/org-invitations/{raw}/accept", headers=auth(invitee_token)
    )
    second = await client.post(
        f"/v1/org-invitations/{raw}/accept", headers=auth(invitee_token)
    )

    assert first.status_code == 200
    assert first.json()["role"] == "member"
    assert second.status_code == 409


async def test_expired_invitation_gone(
    client: AsyncClient, migrated_database: None, clean_invites: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepting an expired invitation returns 410."""
    owner_id = await create_user("exp-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "exp")
    invitee_email = f"exp-invitee-{uuid4().hex[:8]}@auracles.space"
    raw = await invite(client, monkeypatch, org, owner_token, invitee_email)
    async with async_session_factory() as session:
        async with session.begin():
            invitation = await session.scalar(
                select(OrgInvitation).where(OrgInvitation.email == invitee_email)
            )
            invitation.expires_at = datetime.now(UTC) - timedelta(days=1)
    invitee_id = await create_user("exp-invitee-actual")
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, invitee_id)
            user.email = invitee_email

    response = await client.post(
        f"/v1/org-invitations/{raw}/accept",
        headers=auth(create_access_token(invitee_id, [])),
    )

    assert response.status_code == 410


async def test_decline_terminalizes(
    client: AsyncClient, migrated_database: None, clean_invites: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decline flips the invite to declined; preview afterwards → 404."""
    owner_id = await create_user("dec-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "dec")
    invitee_email = f"dec-invitee-{uuid4().hex[:8]}@auracles.space"
    raw = await invite(client, monkeypatch, org, owner_token, invitee_email)
    invitee_id = await create_user("dec-invitee-actual")
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, invitee_id)
            user.email = invitee_email
    invitee_token = create_access_token(invitee_id, [])

    declined = await client.post(
        f"/v1/org-invitations/{raw}/decline", headers=auth(invitee_token)
    )
    preview = await client.get(f"/v1/org-invitations/{raw}", headers=auth(invitee_token))

    assert declined.status_code == 204
    assert preview.status_code == 404
```

- [ ] **Step 2: Run to verify failure** — expected 404s.

- [ ] **Step 3: Implement** — service:

```python
async def _get_live_invitation(db: AsyncSession, token: str) -> tuple[OrgInvitation, Organization]:
    """Resolve a pending, unexpired invitation + its active org by raw token.

    Raises:
        HTTPException(404): Unknown token, terminal status, or dead org.
        HTTPException(410): Pending but past expires_at.
    """
    invitation = await db.scalar(
        select(OrgInvitation).where(OrgInvitation.token_hash == hash_token(token))
    )
    if invitation is None or invitation.status != "pending":
        code = status.HTTP_409_CONFLICT if invitation is not None else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail="Invitation is not available.")
    org = await db.scalar(
        select(Organization).where(
            Organization.id == invitation.org_id,
            Organization.deactivated_at.is_(None),
            Organization.suspended_at.is_(None),
        )
    )
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation is not available.")
    if invitation.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invitation has expired.")
    return invitation, org
```

`accept_invitation(db, *, user, token) -> MyOrganizationResponse`: `_get_live_invitation`, email match (`user.email.lower() != invitation.email` → 403), transaction: create `OrgMember(role=invitation.role)`, set `status="accepted"`, `responded_at=now`, audit `org_member_joined`, notify inviter via `create_notification(..., "org_invitation_accepted", dedupe_key=f"org-invite-accepted-{invitation.id}")`; after commit call `await sync_derived_roles(db, user_id=user.id)`; return the `MyOrganizationResponse` shape from Task 2. `decline_invitation` mirrors it (no member row, status `declined`, notification `org_invitation_declined`). `preview_invitation` returns `OrgInvitationPreviewResponse(org_name=org.name, org_slug=org.slug, role=invitation.role, expires_at=invitation.expires_at)`. Router adds the three `/org-invitations/{token}` routes using plain `CurrentUser` (no org role — the caller is not a member yet).

Note the semantics choice: unknown token → 404, known-but-terminal → 409, expired-pending → 410, wrong email → 403. The 409-on-terminal satisfies "second accept of the same token → 409" (idempotency rule).

- [ ] **Step 4: Run full invitation suite** — `uv run pytest tests/integration/test_org_invitations_endpoints.py -v` → PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy app
git add app/modules/organizations/ tests/integration/test_org_invitations_endpoints.py
git commit -m "Add org invitation preview, accept, and decline"
```

---

### Task 8: Beat expiry sweep

**Files:**
- Create: `backend/app/workers/tasks/organizations_beat.py`
- Modify: `backend/app/workers/beat_schedule.py` (one entry)
- Test: `backend/tests/unit/workers/test_organizations_beat.py`

**Interfaces:**
- Produces Celery task `expire_org_invitations()` — flips `pending` invitations with `expires_at < now()` to `expired`; idempotent; returns count. Beat entry `expire-org-invitations` daily at 03:20 UTC: `crontab(hour=3, minute=20)`.

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/workers/test_organizations_beat.py` (async engine + session pattern from existing `tests/unit/workers/` files; seed one pending-expired, one pending-live, one declined invitation; run `expire_org_invitations.apply()`):

```python
async def test_expiry_sweep_flips_only_stale_pending() -> None:
    """The sweep expires overdue pending invites and touches nothing else."""
    # seed rows (org + 3 invitations) ...
    result = expire_org_invitations.apply()
    assert result.successful()
    # reload: overdue -> "expired", live -> "pending", declined -> "declined"


async def test_expiry_sweep_idempotent() -> None:
    """Running the sweep twice yields the same terminal state."""
    expire_org_invitations.apply()
    second = expire_org_invitations.apply()
    assert second.successful()
```

(Write the seeding inline with the models — full code in the test file; follow the sync-session bridge used by the existing beat task tests, e.g. `tests/unit/workers/test_gdpr_beat.py` if present, else `asgiref`/`asyncio.run` pattern used by neighbors in that directory.)

- [ ] **Step 2: Run to verify failure** — import error.

- [ ] **Step 3: Implement**

```python
"""Celery Beat sweep for organization invitations."""

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import update

from app.core.database import async_session_factory
from app.modules.organizations.models import OrgInvitation
from app.workers.celery_app import app
from app.workers.utils import run_async  # use the same async-bridge the other beat tasks use


@app.task(bind=True)  # type: ignore[untyped-decorator]
def expire_org_invitations(self) -> int:
    """Mark overdue pending org invitations as expired. Idempotent."""

    async def _sweep() -> int:
        async with async_session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    update(OrgInvitation)
                    .where(
                        OrgInvitation.status == "pending",
                        OrgInvitation.expires_at < datetime.now(UTC),
                    )
                    .values(status="expired", responded_at=datetime.now(UTC))
                )
            return result.rowcount or 0

    count = run_async(_sweep())
    logger.bind(
        module="organizations", action="expire_org_invitations", task_id=self.request.id
    ).info(f"expired {count} invitations")
    return count
```

(If `app.workers.utils.run_async` doesn't exist, use the exact async-bridge idiom found in `app/workers/tasks/gdpr_beat.py` — copy its import, don't invent one.) Beat entry in `beat_schedule.py`:

```python
"expire-org-invitations": {
    "task": "app.workers.tasks.organizations_beat.expire_org_invitations",
    "schedule": crontab(hour=3, minute=20),
},
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/unit/workers/test_organizations_beat.py -v
uv run ruff check . && uv run mypy app
git add app/workers/ tests/unit/workers/test_organizations_beat.py
git commit -m "Add daily org invitation expiry sweep"
```

---

### Task 9: Teams

**Files:**
- Create: `backend/migrations/versions/2026_07_03_0061_org_teams.py`
- Modify: `backend/app/modules/organizations/models.py` (add `OrgTeam`, `OrgTeamMember`)
- Modify: `backend/app/modules/organizations/{schemas,service,router}.py`
- Test: `backend/tests/integration/test_org_teams_endpoints.py`

**Interfaces:**
- Produces:
  - `OrgTeam(id, org_id FK CASCADE, name, created_at)`, `UNIQUE(org_id, name)`; `OrgTeamMember(team_id FK org_teams CASCADE, member_id FK org_members CASCADE, PK(team_id, member_id))`.
  - Service: `create_team` (admin+, 409 duplicate name, audits `org_team_created`), `list_teams` (member+, includes `member_count`), `rename_team` (admin+, 409 duplicate), `delete_team` (admin+, audits `org_team_deleted`), `add_team_member` (admin+, member must belong to org, idempotent PUT → 204 both first time and repeat), `remove_team_member` (admin+, 204; 404 when not in team).
  - Routes exactly per spec under `/orgs/{org_id}/teams`.
- Key behavior test: removing a member from the org (Task 4's `remove_member`) cascades them out of all teams — FK `ON DELETE CASCADE` on `org_team_members.member_id` does this at the DB layer; test proves it.

- [ ] **Step 1: Write failing tests** — `backend/tests/integration/test_org_teams_endpoints.py` with full code following the established fixture pattern; cover: create team (201) + duplicate name (409); add member to team (204) + non-org-member (404) + idempotent repeat (204); list teams shows member_count; delete team (204); **org-removal cascade**:

```python
async def test_org_removal_cascades_out_of_teams(
    client: AsyncClient, migrated_database: None, clean_teams: None
) -> None:
    """Removing a member from the org removes them from every team."""
    owner_id = await create_user("casc-owner")
    member_id = await create_user("casc-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "casc")
    member_row = await add_member(org["id"], member_id, "member")
    team = await client.post(
        f"/v1/orgs/{org['id']}/teams", json={"name": "Reviewers"}, headers=auth(owner_token)
    )
    team_id = team.json()["id"]
    added = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/members/{member_row}",
        headers=auth(owner_token),
    )
    assert added.status_code == 204

    removed = await client.delete(
        f"/v1/orgs/{org['id']}/members/{member_row}", headers=auth(owner_token)
    )

    assert removed.status_code == 204
    async with async_session_factory() as session:
        remaining = (
            await session.scalars(
                select(OrgTeamMember).where(OrgTeamMember.team_id == UUID(team_id))
            )
        ).all()
    assert remaining == []
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — models mirror the established column patterns; migration 0061 mirrors 0058 (two tables + `idx_org_team_members_member` index; downgrade drops both). Schemas: `OrgTeamCreateRequest(name: str = Field(min_length=2, max_length=80))`, `OrgTeamRenameRequest(name)`, `OrgTeamResponse(id, name, member_count, created_at)`, `OrgTeamsResponse(teams: list[OrgTeamResponse])`. Service functions are small transactional wrappers; `add_team_member` validates the member belongs to this org (`_get_member_row`) and uses `INSERT ... ON CONFLICT DO NOTHING` (`pg_insert(OrgTeamMember).on_conflict_do_nothing()`) for idempotency.
- [ ] **Step 4: Run tests + migration round-trip.**
- [ ] **Step 5: Lint, type-check, commit**

```bash
git add migrations/versions/2026_07_03_0061_org_teams.py app/modules/organizations/ tests/integration/test_org_teams_endpoints.py
git commit -m "Add org teams with membership and org-removal cascade"
```

---

### Task 10: Derived attestor-role sync

**Files:**
- Modify: `backend/app/modules/organizations/service.py` (complete `sync_derived_roles`)
- Test: `backend/tests/unit/modules/test_organizations_service.py`

**Interfaces:**
- Consumes: `app.modules.auth.models.UserRole` (`user_id`, `role`, `approved_at`, unique `(user_id, role)`).
- Produces the final `sync_derived_roles(db, *, user_id: UUID) -> None`:
  - Grant: user belongs to ≥1 org whose `attestor` capability is `active` AND has no `UserRole(role='attestor')` row → insert one with `approved_at=now()`, audit `org_capability_status_changed`-adjacent metadata (`action="attestor_role_granted"` is NOT in the audit list — use `write_audit(action="role_changed", target_type="user", ...)` if a `role_changed` action already exists in the codebase; otherwise audit as `org_derived_role_synced`).
  - Revoke: no qualifying org and an `attestor` role row exists → delete it.
  - Idempotent both directions. Runs in its own transaction (`async with db.begin()` guarded by the in-transaction rollback idiom).

- [ ] **Step 1: Write failing unit tests** — in `backend/tests/unit/modules/test_organizations_service.py` (async fixtures with real DB, per existing unit test files): three tests — grant when active-attestor org membership exists; revoke when last membership removed; no-op when nothing changes (call twice, assert single role row).

```python
async def test_sync_grants_attestor_role_for_active_org_member() -> None:
    """Membership in an active-attestor org grants the derived user role."""
    # seed: user, org, OrgMember, OrgCapability(attestor, active)
    await sync_derived_roles(db, user_id=user_id)
    role = await db.scalar(
        select(UserRole).where(UserRole.user_id == user_id, UserRole.role == "attestor")
    )
    assert role is not None


async def test_sync_revokes_when_no_qualifying_org() -> None:
    """Losing the last active-attestor org membership revokes the role."""
    # seed role row + no qualifying membership
    await sync_derived_roles(db, user_id=user_id)
    assert await db.scalar(
        select(UserRole).where(UserRole.user_id == user_id, UserRole.role == "attestor")
    ) is None


async def test_sync_idempotent() -> None:
    """Running the sync twice leaves exactly one role row."""
    await sync_derived_roles(db, user_id=user_id)
    await sync_derived_roles(db, user_id=user_id)
    count = await db.scalar(
        select(func.count()).select_from(UserRole).where(
            UserRole.user_id == user_id, UserRole.role == "attestor"
        )
    )
    assert count == 1
```

(Seeding code written out fully in the test file; use the existing unit-test DB fixture pattern from `tests/unit/modules/test_attestation_service.py` neighbors.)

- [ ] **Step 2: Run to verify failure** — grant test fails (current stub is a no-op).
- [ ] **Step 3: Implement**

```python
async def sync_derived_roles(db: AsyncSession, *, user_id: UUID) -> None:
    """Grant/revoke the derived user-level attestor role for this user.

    The attestor role is org-derived (spec decision 9): held while the
    user belongs to at least one org whose attestor capability is active.
    Idempotent; safe on every membership or capability change.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        qualifying = await db.scalar(
            select(func.count())
            .select_from(OrgMember)
            .join(OrgCapability, OrgCapability.org_id == OrgMember.org_id)
            .join(Organization, Organization.id == OrgMember.org_id)
            .where(
                OrgMember.user_id == user_id,
                OrgCapability.capability == "attestor",
                OrgCapability.status == "active",
                Organization.deactivated_at.is_(None),
                Organization.suspended_at.is_(None),
            )
        )
        existing = await db.scalar(
            select(UserRole).where(
                UserRole.user_id == user_id, UserRole.role == "attestor"
            )
        )
        if qualifying and existing is None:
            db.add(UserRole(user_id=user_id, role="attestor", approved_at=datetime.now(UTC)))
            await write_audit(
                db=db, actor_id=None, action="org_derived_role_synced",
                target_type="user", target_id=user_id,
                metadata={"role": "attestor", "granted": True},
            )
        elif not qualifying and existing is not None:
            await db.delete(existing)
            await write_audit(
                db=db, actor_id=None, action="org_derived_role_synced",
                target_type="user", target_id=user_id,
                metadata={"role": "attestor", "granted": False},
            )
```

(Import `UserRole` from `app.modules.auth.models`. Check `UserRole`'s required columns at `app/modules/auth/models.py:177` — if `approved_at` is non-nullable or named differently, match the real model.)

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/unit/modules/test_organizations_service.py -v
uv run ruff check . && uv run mypy app
git add app/modules/organizations/service.py tests/unit/modules/test_organizations_service.py
git commit -m "Complete derived attestor-role sync from org membership"
```

---

### Task 11: Platform-admin list + suspend

**Files:**
- Modify: `backend/app/modules/organizations/{schemas,service,router}.py`
- Test: `backend/tests/integration/test_org_admin_endpoints.py`

**Interfaces:**
- Consumes: `require_role("admin")` from `app.core.dependencies` (platform admin, not org admin).
- Produces:
  - `GET /v1/admin/orgs?query=&page=&page_size=` → `AdminOrgsResponse(orgs: list[AdminOrgResponse], total, page, page_size)`; `AdminOrgResponse(id, slug, name, country, member_count, capabilities: dict[str,str], suspended_at, deactivated_at, created_at)`; `query` matches slug/name ILIKE.
  - `POST /v1/admin/orgs/{org_id}/suspend` → 204; sets `suspended_at=now()`; audits `org_suspended`; idempotent (already suspended → 204). Suspension lockout already enforced by `require_org_role` (Task 3) — test proves an org admin gets 403 `org_suspended` after suspension. Calls `sync_derived_roles` for every member of the org (suspended org no longer qualifies).
  - Routes live in this module's router with `/admin/orgs` paths (consistent with `list_attestor_applications_for_admin` living in the attestation module).

- [ ] **Step 1: Write failing tests** — `backend/tests/integration/test_org_admin_endpoints.py` full code, fixture pattern as before; platform admin user created with `create_access_token(admin_id, ["admin"])` (plus a `UserRole(role="admin")` row if `require_role` checks DB — it checks token claims only, so token roles suffice); tests: non-admin → 403; list returns created org with member_count; suspend → 204 and subsequent org-admin PATCH on the org → 403 with `error_code == "org_suspended"`; suspend twice → 204.

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — service `admin_list_orgs` (paginated select with counts, ILIKE filter) and `admin_suspend_org` (transaction, set timestamp if null, audit, then `sync_derived_roles` per member user_id). Router:

```python
PlatformAdmin = Annotated[User, Depends(require_role("admin"))]


@router.get("/admin/orgs", response_model=AdminOrgsResponse)
async def admin_list_orgs(
    admin: PlatformAdmin,
    db: DatabaseSession,
    query: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminOrgsResponse:
    """List/search organizations for platform administration."""
    return await service.admin_list_orgs(db=db, query=query, page=page, page_size=page_size)


@router.post("/admin/orgs/{org_id}/suspend", status_code=status.HTTP_204_NO_CONTENT)
async def admin_suspend_org(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Suspend an organization platform-wide (idempotent)."""
    await service.admin_suspend_org(db=db, admin=admin, org_id=org_id)
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/integration/test_org_admin_endpoints.py -v
uv run ruff check . && uv run mypy app
git add app/modules/organizations/ tests/integration/test_org_admin_endpoints.py
git commit -m "Add platform-admin org list and suspend"
```

---

### Task 12: GDPR touchpoints

**Files:**
- Modify: `backend/app/modules/gdpr/export_service.py` (add org memberships section to the export bundle assembly)
- Modify: `backend/app/modules/gdpr/deletion_service.py` (add sole-owner blocker to `request_account_deletion`'s blocker assembly)
- Modify: `backend/app/modules/organizations/service.py` (add the two helpers below)
- Test: extend the existing GDPR test files (`backend/tests/unit/modules/` — locate the current export/deletion test modules and add cases there, following their fixtures)

**Interfaces:**
- Produces in `organizations/service.py`:

```python
async def export_user_org_memberships(db: AsyncSession, *, user_id: UUID) -> list[dict[str, object]]:
    """Return the user's org memberships for the GDPR export bundle."""
    rows = (
        await db.execute(
            select(Organization.slug, Organization.name, OrgMember.role, OrgMember.joined_at)
            .join(OrgMember, OrgMember.org_id == Organization.id)
            .where(OrgMember.user_id == user_id)
        )
    ).all()
    return [
        {"org_slug": slug, "org_name": name, "role": role, "joined_at": joined_at.isoformat()}
        for slug, name, role, joined_at in rows
    ]


async def user_deletion_org_blockers(db: AsyncSession, *, user_id: UUID) -> list[str]:
    """Names of orgs blocking account deletion (sole owner + active capability)."""
    rows = (
        await db.execute(
            select(Organization.name)
            .join(OrgMember, OrgMember.org_id == Organization.id)
            .join(OrgCapability, OrgCapability.org_id == Organization.id)
            .where(
                OrgMember.user_id == user_id,
                OrgMember.role == "owner",
                OrgCapability.status == "active",
                Organization.deactivated_at.is_(None),
            )
            .distinct()
        )
    ).all()
    return [name for (name,) in rows]
```

- Export: call `export_user_org_memberships` where the other sections are assembled and add key `"organization_memberships"` to the bundle dict.
- Deletion: call `user_deletion_org_blockers`; non-empty → append blocker string(s) `f"Transfer ownership or wind down organization '{name}' before deleting your account."` to the existing blocked-response path (409 shape already exists).
- Read both GDPR service files first and slot into their existing assembly points; do not restructure them.

- [ ] **Step 1: Write failing tests** — in the existing GDPR unit test modules: (a) export bundle contains `organization_memberships` with the seeded org; (b) deletion request by a sole owner of an org with an active capability → 409 blocked; (c) same user after ownership transfer → not blocked by orgs. Full seeding code in the tests using organizations models.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement the two helpers + the two call-site edits.**
- [ ] **Step 4: Run the GDPR test modules + the whole suite for regressions:**

```bash
uv run pytest tests/ -x -q
```

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy app
git add app/modules/gdpr/ app/modules/organizations/service.py tests/
git commit -m "Include org memberships in GDPR export; block deletion for sole owners"
```

---

### Task 13: OpenAPI contract + frontend client regen

**Files:**
- Modify: `contracts/openapi.yaml` (all Org Core paths + schemas)
- Regenerate: `frontend/src/lib/generated/*` via `cd frontend && npm run generate:api`

**Interfaces:**
- Contract paths added (mirror the implemented routers exactly — operation ids follow FastAPI's generated pattern used throughout the file, e.g. `create_organization_v1_orgs_post`): `/v1/orgs`, `/v1/orgs/mine`, `/v1/orgs/{slug}`, `/v1/orgs/{org_id}` (PATCH/DELETE), `/v1/orgs/{org_id}/members` + `/{member_id}`, `/v1/orgs/{org_id}/transfer-ownership`, `/v1/orgs/{org_id}/invitations` + `/{invitation_id}`, `/v1/org-invitations/{token}` (+ `/accept`, `/decline`), `/v1/orgs/{org_id}/teams` + `/{team_id}` + `/members/{member_id}`, `/v1/admin/orgs`, `/v1/admin/orgs/{org_id}/suspend`.
- Schemas: mirror the Pydantic models 1:1 (component names = class names, as elsewhere in the file).

- [ ] **Step 1: Extract the live schema and diff against the contract**

```bash
cd /Users/a0000/projects/auracles/backend
uv run python -c "
import json
from app.main import app
print(json.dumps(app.openapi(), indent=2))
" > /tmp/live-openapi.json
```

Use the generated JSON as the source for the new paths/components; hand-merge them into `contracts/openapi.yaml` in the same style as the existing entries (the contract is hand-maintained YAML — merge, don't overwrite).

- [ ] **Step 2: Validate the contract**

Run: `uv run openapi-spec-validator ../contracts/openapi.yaml`
Expected: no output (valid).

- [ ] **Step 3: Regenerate the frontend client**

```bash
cd /Users/a0000/projects/auracles/frontend && npm run generate:api
git status --short src/lib/generated
```

Expected: `sdk.gen.ts` / `types.gen.ts` modified. CI diffs regenerated output, so these files must be committed.

- [ ] **Step 4: Frontend typecheck delta check**

Run: `cd /Users/a0000/projects/auracles/frontend && pnpm typecheck; true`
Expected: the same 10 pre-existing attestation-drift errors as on main — **zero new errors** from Org Core (nothing consumes the new client surface yet). If new errors appear, the contract merge is wrong — fix the contract, not the components.

- [ ] **Step 5: Full backend suite + lint gate, then commit**

```bash
cd /Users/a0000/projects/auracles/backend
uv run pytest tests/ -q
uv run ruff check . && uv run mypy app
cd /Users/a0000/projects/auracles
git add contracts/openapi.yaml frontend/src/lib/generated
git commit -m "Add Organizations Core endpoints to OpenAPI contract"
```

---

## Self-Review (performed)

- **Spec coverage:** every spec section maps to a task — data model (1, 6, 9), API surface (2–7, 9, 11), RBAC + security (3, 6, 11), invitation flow (6, 7, 8), derived role sync (4-stub, 10), error handling (throughout, asserted in tests), GDPR (12), audit (each write path), rate limit (6), contract (13). Deactivation-blocked-by-capability: Task 3. Suspension lockout: Tasks 3 + 11.
- **Placeholder scan:** Task 4 ships `sync_derived_roles` as an explicit documented no-op completed by Task 10 — intentional wiring order, not a placeholder; Tasks 8/10/12 defer to *named existing patterns* (exact file references) where inventing code here would be less accurate than the codebase itself.
- **Type consistency:** `OrgContext(org, member, user)` used consistently; `sync_derived_roles(db, *, user_id)` keyword signature identical at all call sites (Tasks 4, 7, 10, 11); `hash_token` / `RateLimiter` / `write_audit` signatures match `app/core/*.py` as verified during plan research.
