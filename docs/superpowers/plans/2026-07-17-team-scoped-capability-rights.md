# Team-Scoped Org Capability Rights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make org marketplace rights (contributor/operator/attestor) flow from team membership instead of being granted to every org member.

**Architecture:** An org capability stays the eligibility gate (`OrgCapability.status == "active"`). A new link table `org_team_capabilities` records which capabilities each team grants. The single shared `sync_derived_roles` is rewritten so a user holds a derived role iff the org capability is active AND the member is owner/admin (implicit) OR sits on a team that has the capability enabled. Every team/membership mutation re-syncs affected members. A backfill migration puts all current members into an "All members" team so nobody loses access.

**Tech Stack:** SQLAlchemy async, FastAPI, Alembic, Pydantic v2, pytest/pytest-asyncio (backend); Next.js 15, TypeScript, vitest + @testing-library/react, hey-api SDK (frontend).

## Global Constraints

- Work directly on `main`. Do not create branches without asking.
- Commit messages end at the last meaningful line — NO `Co-Authored-By` trailer.
- TDD strictly RED→GREEN, one behavior at a time (vertical slices, never all-tests-then-all-code).
- OpenAPI-first: update `contracts/openapi.yaml` before implementing a new endpoint, regenerate the frontend client after.
- RBAC enforced at the FastAPI dependency layer (`OrgAdmin`), never inside services.
- Backend logging via `loguru`; audit security actions via `write_audit`.
- Migration filenames `YYYY_MM_DD_NNNN_description.py`; `alembic upgrade head` and `alembic downgrade -1` must both succeed.
- Reuse the existing PG enum `org_capability_enum` (values: `attestor`, `contributor`, `operator`); `create_type=False`.
- Full-repo lint/type before claiming clean: `cd backend && uv run ruff check . && uv run mypy app`; frontend `npx tsc --noEmit && npx eslint`.
- All backend commands run from `backend/`. Frontend commands run from `frontend/`.

## Behavior Change (expected, not a regression)

Before: activating an org capability granted the derived role to **every** member. After: activation grants it to **owner/admin only**; plain members receive it via an enabled team. Existing tests that assert a plain member gains the role on activation must be updated to the new semantics (Task 2, Step 6). This is intended per the spec.

## File Structure

**Backend**
- `app/modules/organizations/models.py` — add `OrgTeamCapability` model.
- `migrations/versions/2026_07_17_0089_add_org_team_capabilities.py` — create table + backfill (new).
- `app/modules/organizations/service.py` — rewrite `sync_derived_roles`; add `_sync_team_member_roles`, `enable_team_capability`, `disable_team_capability`; re-sync wiring in `add_team_member`/`remove_team_member`/`delete_team`/`change_member_role`; capabilities in `list_teams`.
- `app/modules/organizations/schemas.py` — `capabilities` field on `OrgTeamResponse`; `OrgCapabilityName` Literal.
- `app/modules/organizations/router.py` — PUT/DELETE team-capability endpoints.
- `contracts/openapi.yaml` — two endpoints + team `capabilities` field.

**Backend tests**
- `tests/unit/modules/test_org_derived_roles.py` — extend sync matrix.
- `tests/unit/modules/test_org_team_capabilities.py` — service unit tests (new).
- `tests/integration/test_org_team_capability_endpoints.py` — endpoint tests (new).
- `tests/integration/test_org_teams_endpoints.py` — capabilities in list response.
- Update: `tests/integration/test_org_operator_capability_endpoints.py`, `tests/integration/test_org_contributor_capability_endpoints.py`.

**Frontend**
- `src/lib/generated/*` — regenerated SDK.
- `src/components/modules/organizations/organization-teams.tsx` — per-team capability toggles.
- `src/components/modules/organizations/organization-capabilities.tsx` — copy update.
- `src/components/modules/organizations/organization-teams.test.tsx` — toggle tests.

---

### Task 1: Table + backfill migration

**Files:**
- Modify: `backend/app/modules/organizations/models.py` (after `OrgTeamMember`, ~line 263)
- Create: `backend/migrations/versions/2026_07_17_0089_add_org_team_capabilities.py`
- Test: `backend/tests/integration/test_org_team_capabilities_migration.py` (new)

**Interfaces:**
- Consumes: existing `ORG_CAPABILITY_ENUM`, `CreatedAtMixin`, `Base`; head revision `2026_07_17_0088`.
- Produces: `OrgTeamCapability(team_id: UUID, capability: str, created_at)`, table `org_team_capabilities`, PK `(team_id, capability)`.

- [ ] **Step 1: Write the failing migration test**

Create `backend/tests/integration/test_org_team_capabilities_migration.py`:

```python
"""Migration test: org_team_capabilities table + backfill.

Backfilling an "All members" team for every org with an active capability must
preserve access — the same members keep their derived roles after the switch to
team-scoped rights.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]

DOWN = "2026_07_17_0088"
UP = "2026_07_17_0089"


@pytest.fixture
def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def test_backfill_creates_all_members_team_and_enables_caps(
    alembic_config: Config,
) -> None:
    """After upgrade, an org with an active capability has an All members team
    containing its member with the capability enabled."""
    command.upgrade(alembic_config, DOWN)
    sync_engine = create_engine(
        __import__("app.main", fromlist=["app"]).app.state.settings.sync_database_url
    )
    org_id = "11111111-1111-1111-1111-111111111111"
    user_id = "22222222-2222-2222-2222-222222222222"
    try:
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO users (id, email, email_verified) "
                    "VALUES (:u, 'mig-team@auracles.space', true) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"u": user_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO organizations (id, name, slug, country, created_by) "
                    "VALUES (:o, 'Mig Org', 'mig-team-org', 'US', :u)"
                ),
                {"o": org_id, "u": user_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO org_members (org_id, user_id, role) "
                    "VALUES (:o, :u, 'member')"
                ),
                {"o": org_id, "u": user_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO org_capabilities (org_id, capability, status) "
                    "VALUES (:o, 'operator', 'active')"
                ),
                {"o": org_id},
            )

        command.upgrade(alembic_config, UP)

        with sync_engine.connect() as conn:
            team = conn.execute(
                sa.text(
                    "SELECT id FROM org_teams "
                    "WHERE org_id=:o AND name='All members'"
                ),
                {"o": org_id},
            ).fetchone()
            assert team is not None
            team_id = team[0]
            member_count = conn.execute(
                sa.text(
                    "SELECT count(*) FROM org_team_members WHERE team_id=:t"
                ),
                {"t": team_id},
            ).scalar()
            assert member_count == 1
            caps = conn.execute(
                sa.text(
                    "SELECT capability FROM org_team_capabilities WHERE team_id=:t"
                ),
                {"t": team_id},
            ).scalars().all()
            assert caps == ["operator"]
    finally:
        with sync_engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM org_members WHERE org_id=:o"), {"o": org_id})
            conn.execute(sa.text("DELETE FROM organizations WHERE id=:o"), {"o": org_id})
            conn.execute(sa.text("DELETE FROM users WHERE id=:u"), {"u": user_id})
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()
```

> The `organizations` NOT NULL columns are `slug`, `name`, `country`, `created_by` (verified against the `Organization` model); the INSERT above sets all of them (`created_by` reuses the seeded user). The assertions on `org_teams`/`org_team_members`/`org_team_capabilities` are the behavior under test.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_org_team_capabilities_migration.py -v`
Expected: FAIL — revision `2026_07_17_0089` does not exist / table missing.

- [ ] **Step 3: Add the model**

In `backend/app/modules/organizations/models.py`, after the `OrgTeamMember` class (~line 263):

```python
class OrgTeamCapability(CreatedAtMixin, Base):
    """A marketplace capability granted to every member of one team.

    A member holds the derived role for a capability when the org capability is
    active and the member is owner/admin or sits on a team with a matching row.
    """

    __tablename__ = "org_team_capabilities"

    team_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("org_teams.id", ondelete="CASCADE"),
        primary_key=True,
    )
    capability: Mapped[str] = mapped_column(
        ORG_CAPABILITY_ENUM, primary_key=True
    )
```

- [ ] **Step 4: Write the migration**

Create `backend/migrations/versions/2026_07_17_0089_add_org_team_capabilities.py`:

```python
"""Add org_team_capabilities and backfill an All members team per org.

Team-scoped capability rights: a marketplace role is now granted through team
membership, not to every org member. This creates the team↔capability link
table and backfills existing orgs — every org with an active capability gets an
"All members" team containing all current members with those capabilities
enabled — so nobody loses access at cutover.

Revision ID: 2026_07_17_0089
Revises: 2026_07_17_0088
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_17_0089"
down_revision: str | Sequence[str] | None = "2026_07_17_0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the link table, then backfill All members teams."""
    op.create_table(
        "org_team_capabilities",
        sa.Column(
            "team_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org_teams.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "capability",
            sa.dialects.postgresql.ENUM(
                "attestor", "contributor", "operator",
                name="org_capability_enum",
                create_type=False,
            ),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    conn = op.get_bind()
    org_ids = conn.execute(
        sa.text(
            "SELECT DISTINCT org_id FROM org_capabilities WHERE status = 'active'"
        )
    ).scalars().all()

    for org_id in org_ids:
        team_id = conn.execute(
            sa.text(
                "SELECT id FROM org_teams "
                "WHERE org_id = :o AND name = 'All members'"
            ),
            {"o": org_id},
        ).scalar()
        if team_id is None:
            team_id = conn.execute(
                sa.text(
                    "INSERT INTO org_teams (org_id, name) "
                    "VALUES (:o, 'All members') RETURNING id"
                ),
                {"o": org_id},
            ).scalar()
        conn.execute(
            sa.text(
                "INSERT INTO org_team_members (team_id, member_id) "
                "SELECT :t, id FROM org_members WHERE org_id = :o "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": team_id, "o": org_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO org_team_capabilities (team_id, capability) "
                "SELECT :t, capability FROM org_capabilities "
                "WHERE org_id = :o AND status = 'active' "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": team_id, "o": org_id},
        )


def downgrade() -> None:
    """Drop the link table. Backfilled teams remain as ordinary teams."""
    op.drop_table("org_team_capabilities")
```

- [ ] **Step 5: Run the migration test to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_org_team_capabilities_migration.py -v`
Expected: PASS.

- [ ] **Step 6: Verify upgrade/downgrade round-trip**

Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: all three succeed, exit 0.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/organizations/models.py backend/migrations/versions/2026_07_17_0089_add_org_team_capabilities.py backend/tests/integration/test_org_team_capabilities_migration.py
git commit -m "feat(orgs): add org_team_capabilities table and backfill migration"
```

---

### Task 2: Rewrite `sync_derived_roles`

**Files:**
- Modify: `backend/app/modules/organizations/service.py:860-931` (`sync_derived_roles`)
- Test: `backend/tests/unit/modules/test_org_derived_roles.py`
- Update: `backend/tests/integration/test_org_operator_capability_endpoints.py`, `backend/tests/integration/test_org_contributor_capability_endpoints.py`

**Interfaces:**
- Consumes: `OrgTeamCapability` (Task 1), existing `OrgMember`, `OrgCapability`, `Organization`, `OrgTeam`, `OrgTeamMember`, `_DERIVED_ROLE_MAP`.
- Produces: same `sync_derived_roles(db, *, user_id)` signature and grant/revoke behavior; the eligibility rule now includes owner/admin-implicit + team-scoped members.

- [ ] **Step 1: Write a failing test — owner implicit, plain member team-gated**

Add to `backend/tests/unit/modules/test_org_derived_roles.py`. Reuse the file's existing `migrated_database`, `org_derived_role_state`, `_create_user` fixtures/helpers. First, extend the `cleanup()` in `org_derived_role_state` to also clear the new tables (add these deletes **before** the existing `delete(OrgCapability)`):

```python
from app.modules.organizations.models import (
    OrgTeam,
    OrgTeamCapability,
    OrgTeamMember,
)
# inside cleanup(), before delete(OrgCapability):
await session.execute(delete(OrgTeamCapability))
await session.execute(delete(OrgTeamMember))
await session.execute(delete(OrgTeam))
```

Then add the test:

```python
async def test_owner_holds_role_without_team(
    migrated_database: None, org_derived_role_state: None
) -> None:
    """An org owner holds the derived operator role from an active capability
    with no team membership (owner/admin implicit)."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("owner")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Imp Org", slug="imp-org", country="US", created_by=owner.id
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="active")
            )

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=owner.id)

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == owner.id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )
        assert role is not None
```

> If `Organization(name=..., slug=...)` does not match the real required columns, mirror the construction used elsewhere in this test file / the org factory. Keep the assertion identical.

- [ ] **Step 2: Run to verify it fails or passes for the wrong reason**

Run: `cd backend && uv run pytest tests/unit/modules/test_org_derived_roles.py::test_owner_holds_role_without_team -v`
Expected: PASS already (current code grants all members incl. owner). This locks owner-implicit before the rewrite. Proceed to the discriminating test.

- [ ] **Step 3: Write the discriminating failing test — plain member without team does NOT hold**

```python
async def test_plain_member_without_team_has_no_role(
    migrated_database: None, org_derived_role_state: None
) -> None:
    """A plain member with an active org capability but no enabled team does
    not hold the derived role."""
    del migrated_database, org_derived_role_state
    member = await _create_user("member")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Gate Org", slug="gate-org", country="US", created_by=member.id
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=member.id, role="member"))
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="active")
            )

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=member.id)

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member.id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )
        assert role is None
```

- [ ] **Step 4: Run to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_org_derived_roles.py::test_plain_member_without_team_has_no_role -v`
Expected: FAIL — current code grants the role to all members.

- [ ] **Step 5: Rewrite `sync_derived_roles`**

Replace the per-capability query block in `backend/app/modules/organizations/service.py` (the `for capability, role in _DERIVED_ROLE_MAP.items():` loop, ~lines 870-888). Ensure `or_` is imported from `sqlalchemy` (add to the existing sqlalchemy import if absent). Import `OrgTeam, OrgTeamCapability, OrgTeamMember` at top of the module if not already imported.

```python
    for capability, role in _DERIVED_ROLE_MAP.items():
        team_grant = (
            select(1)
            .select_from(OrgTeamMember)
            .join(OrgTeam, OrgTeam.id == OrgTeamMember.team_id)
            .join(
                OrgTeamCapability,
                (OrgTeamCapability.team_id == OrgTeam.id)
                & (OrgTeamCapability.capability == capability),
            )
            .where(
                OrgTeamMember.member_id == OrgMember.id,
                OrgTeam.org_id == Organization.id,
            )
            .exists()
        )
        stmt = (
            select(1)
            .select_from(OrgMember)
            .join(Organization, Organization.id == OrgMember.org_id)
            .join(
                OrgCapability,
                (OrgCapability.org_id == Organization.id)
                & (OrgCapability.capability == capability)
                & (OrgCapability.status == "active"),
            )
            .where(
                OrgMember.user_id == user_id,
                Organization.suspended_at.is_(None),
                Organization.deactivated_at.is_(None),
                or_(
                    OrgMember.role.in_(("owner", "admin")),
                    team_grant,
                ),
            )
            .limit(1)
        )
        should_have_role_by_name[role] = (await db.scalar(stmt)) is not None
```

Update the function docstring to note the owner/admin-implicit + team-scoped rule.

- [ ] **Step 6: Update existing tests that assumed org-wide grant**

In `tests/integration/test_org_operator_capability_endpoints.py` and `tests/integration/test_org_contributor_capability_endpoints.py`: any assertion that a **plain member** gains the derived role after activation must change to assert the **owner** gains it and the plain member does **not** (until team-assigned). Search each file for role-grant assertions on the member and adjust. Example transform in `test_activate_operator_capability_happy_path`:

```python
    # After activation, owner holds the operator role (implicit); the plain
    # member does not until assigned to an operator-enabled team.
    async with async_session_factory() as session:
        owner_role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == owner_id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )
        member_role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member_id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )
    assert owner_role is not None
    assert member_role is None
```

Mirror for the contributor endpoints file (role `"contributor"`).

- [ ] **Step 6b: Add the remaining rule-branch tests, run them**

Both branches of the rule need direct coverage. Add to `test_org_derived_roles.py`:

```python
async def test_admin_holds_role_without_team(
    migrated_database: None, org_derived_role_state: None
) -> None:
    """An org admin holds the derived role implicitly, with no team."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("owner")
    admin = await _create_user("admin")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Adm Org", slug="adm-org", country="US", created_by=owner.id
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            session.add(OrgMember(org_id=org.id, user_id=admin.id, role="admin"))
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="active")
            )

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=admin.id)

    async with async_session_factory() as session:
        assert await session.scalar(
            select(UserRole).where(
                UserRole.user_id == admin.id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        ) is not None


async def test_inactive_org_capability_revokes_even_owner(
    migrated_database: None, org_derived_role_state: None
) -> None:
    """When the org capability is not active, nobody holds the role — not even
    the owner."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("owner")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Off Org", slug="off-org", country="US", created_by=owner.id
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="suspended")
            )

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=owner.id)

    async with async_session_factory() as session:
        assert await session.scalar(
            select(UserRole).where(
                UserRole.user_id == owner.id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        ) is None
```

Run: `cd backend && uv run pytest tests/unit/modules/test_org_derived_roles.py -k "admin_holds or inactive_org_capability" -v`
Expected: PASS.

- [ ] **Step 7: Run the sync tests + updated capability tests**

Run:
```
cd backend && uv run pytest \
  tests/unit/modules/test_org_derived_roles.py \
  tests/integration/test_org_operator_capability_endpoints.py \
  tests/integration/test_org_contributor_capability_endpoints.py -v
```
Expected: PASS (new discriminating test passes; owner test still passes; updated capability tests pass).

- [ ] **Step 8: Commit**

```bash
git add backend/app/modules/organizations/service.py backend/tests/unit/modules/test_org_derived_roles.py backend/tests/integration/test_org_operator_capability_endpoints.py backend/tests/integration/test_org_contributor_capability_endpoints.py
git commit -m "feat(orgs): scope derived roles to owner/admin plus enabled teams"
```

---

### Task 3: Re-sync helper + team-mutation wiring

**Files:**
- Modify: `backend/app/modules/organizations/service.py` — add `_sync_team_member_roles`; wire re-sync into `add_team_member` (~1948), `remove_team_member` (~1976), `delete_team` (~1864), `change_member_role` (~934).
- Test: `backend/tests/unit/modules/test_org_derived_roles.py`

**Interfaces:**
- Consumes: `sync_derived_roles` (Task 2), `OrgMember`, `OrgTeamMember`.
- Produces: `_sync_team_member_roles(db: AsyncSession, team_id: UUID) -> None`.

- [ ] **Step 1: Write failing test — adding a member to an enabled team grants the role**

Add to `test_org_derived_roles.py`. This test drives capability enable through the yet-unbuilt team wiring; build a helper inline that inserts the enabled-team rows directly, then exercises `add_team_member` via the service. Because `add_team_member` needs an `OrgContext`, construct membership directly and call `sync_derived_roles` through the wiring under test by adding the team member row through the service function.

```python
from app.modules.organizations.service import OrgContext  # if exported; else build context inline


async def test_adding_member_to_enabled_team_grants_role(
    migrated_database: None, org_derived_role_state: None
) -> None:
    """Adding a member to a team that has a capability enabled grants that
    member the derived role."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("owner")
    member = await _create_user("member")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Team Org", slug="team-org", country="US", created_by=owner.id
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            member_row = OrgMember(org_id=org.id, user_id=member.id, role="member")
            session.add(member_row)
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="active")
            )
            team = OrgTeam(org_id=org.id, name="Sellers")
            session.add(team)
            await session.flush()
            session.add(
                OrgTeamCapability(team_id=team.id, capability="operator")
            )
            org_id, team_id, member_row_id = org.id, team.id, member_row.id

    # Build the admin context the service expects and add the member to the team.
    context = await _org_admin_context(org_id, owner.id)  # helper below
    async with async_session_factory() as session:
        await org_service.add_team_member(
            db=session, context=context, team_id=team_id, member_id=member_row_id
        )

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member.id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )
        assert role is not None
```

Add a small context helper near the top of the test module (reuse the real `OrgContext` shape — inspect `service.py` for its fields: it exposes `.org`, `.member`, `.user`):

```python
async def _org_admin_context(org_id: UUID, user_id: UUID):
    """Build an OrgContext for an owner/admin to call team services in tests."""
    from app.modules.organizations.service import OrgContext
    from app.modules.organizations.models import OrgMember as _OM

    async with async_session_factory() as session:
        org = await session.get(Organization, org_id)
        member = await session.scalar(
            select(_OM).where(_OM.org_id == org_id, _OM.user_id == user_id)
        )
        user = await session.get(User, user_id)
    return OrgContext(org=org, member=member, user=user)
```

> If `OrgContext` is a dataclass/pydantic model with different field names, match them exactly (grep `class OrgContext` in `service.py` or `dependencies.py`).

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_org_derived_roles.py::test_adding_member_to_enabled_team_grants_role -v`
Expected: FAIL — `add_team_member` does not re-sync, so no role row.

- [ ] **Step 3: Add `_sync_team_member_roles` and wire the mutations**

In `service.py`, add near `sync_derived_roles`:

```python
async def _sync_team_member_roles(db: AsyncSession, team_id: UUID) -> None:
    """Re-evaluate derived roles for every member of one team.

    Called after any change to a team's roster or its enabled capabilities.
    ``sync_derived_roles`` manages its own transaction, so callers invoke this
    after their own transaction commits.
    """
    user_ids = (
        await db.scalars(
            select(OrgMember.user_id)
            .join(OrgTeamMember, OrgTeamMember.member_id == OrgMember.id)
            .where(OrgTeamMember.team_id == team_id)
        )
    ).all()
    for user_id in user_ids:
        await sync_derived_roles(db, user_id=user_id)
```

Wire the four mutations:

`add_team_member` — after the `async with db.begin():` block, resolve the member's `user_id` and sync it (the added member is not yet in `_sync_team_member_roles` timing-safe, so sync that user directly):

```python
    # (still inside the function, AFTER the async with db.begin() block)
    member = await _get_member_row(db, org_id=org_id, member_id=member_id)
    await sync_derived_roles(db, user_id=member.user_id)
```

`remove_team_member` — capture `user_id` before delete, sync after commit. Inside the `async with db.begin()` block, before `await db.delete(member_row)`, resolve the org member's user_id:

```python
        target = await _get_member_row(db, org_id=org_id, member_id=member_id)
        removed_user_id = target.user_id
        await db.delete(member_row)
    # after the block:
    await sync_derived_roles(db, user_id=removed_user_id)
```

`delete_team` — capture the team's member user_ids before delete, sync after:

```python
        member_user_ids = (
            await db.scalars(
                select(OrgMember.user_id)
                .join(OrgTeamMember, OrgTeamMember.member_id == OrgMember.id)
                .where(OrgTeamMember.team_id == team_id)
            )
        ).all()
        team_name = team.name
        await db.delete(team)
        await write_audit(...)  # unchanged
    # after the block:
    for uid in member_user_ids:
        await sync_derived_roles(db, user_id=uid)
```

`change_member_role` — after the role change commits, sync the target member's user_id (promotion member→admin grants implicit rights). At the end of the function, after the transaction block, add:

```python
    await sync_derived_roles(db, user_id=target.user_id)
```

> `target` is the `OrgMember` row already loaded in `change_member_role`; confirm the variable name in that function and reuse it. If the row is not in scope after the block, re-select `user_id` by `member_id` before the block and store it.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/unit/modules/test_org_derived_roles.py::test_adding_member_to_enabled_team_grants_role -v`
Expected: PASS.

- [ ] **Step 5: Write + run failing test — removing the member revokes the role**

```python
async def test_removing_member_from_team_revokes_role(
    migrated_database: None, org_derived_role_state: None
) -> None:
    """Removing a member from the only team granting a capability revokes the
    derived role."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("owner")
    member = await _create_user("member")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Rev Org", slug="rev-org", country="US", created_by=owner.id
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            m = OrgMember(org_id=org.id, user_id=member.id, role="member")
            session.add(m)
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="active")
            )
            team = OrgTeam(org_id=org.id, name="Sellers")
            session.add(team)
            await session.flush()
            session.add(OrgTeamCapability(team_id=team.id, capability="operator"))
            session.add(OrgTeamMember(team_id=team.id, member_id=m.id))
            org_id, team_id, member_row_id, member_user_id = (
                org.id, team.id, m.id, member.id,
            )

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=member_user_id)

    context = await _org_admin_context(org_id, owner.id)
    async with async_session_factory() as session:
        await org_service.remove_team_member(
            db=session, context=context, team_id=team_id, member_id=member_row_id
        )

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member_user_id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )
        assert role is None
```

Run: `cd backend && uv run pytest tests/unit/modules/test_org_derived_roles.py::test_removing_member_from_team_revokes_role -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/organizations/service.py backend/tests/unit/modules/test_org_derived_roles.py
git commit -m "feat(orgs): re-sync derived roles on team roster and role changes"
```

---

### Task 4: Enable/disable capability service methods

**Files:**
- Modify: `backend/app/modules/organizations/service.py` — add `enable_team_capability`, `disable_team_capability`.
- Test: `backend/tests/unit/modules/test_org_team_capabilities.py` (new)

**Interfaces:**
- Consumes: `_sync_team_member_roles` (Task 3), `OrgTeamCapability` (Task 1), `write_audit`, `OrgContext`, `pg_insert` (already imported for `add_team_member`).
- Produces:
  - `enable_team_capability(db, *, context: OrgContext, team_id: UUID, capability: str) -> None`
  - `disable_team_capability(db, *, context: OrgContext, team_id: UUID, capability: str) -> None`

- [ ] **Step 1: Write failing test — enable requires active org capability**

Create `backend/tests/unit/modules/test_org_team_capabilities.py`. Reuse the derived-role test fixtures via import, or replicate the `migrated_database` / cleanup pattern. Minimal version:

```python
"""Unit tests for team-capability enable/disable service methods."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.auth.models import User, UserRole
from app.modules.organizations import service as org_service
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
    OrgTeam,
    OrgTeamCapability,
    OrgTeamMember,
)
# Reuse fixtures + helpers from the derived-role suite.
from tests.unit.modules.test_org_derived_roles import (  # noqa: F401
    migrated_database,
    org_derived_role_state,
    _create_user,
    _org_admin_context,
)

pytestmark = pytest.mark.asyncio


async def test_enable_requires_active_org_capability(
    migrated_database: None, org_derived_role_state: None
) -> None:
    """Enabling a capability on a team while the org capability is inactive
    raises 422."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("owner")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Guard Org", slug="guard-org", country="US", created_by=owner.id
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            team = OrgTeam(org_id=org.id, name="Sellers")
            session.add(team)
            await session.flush()
            org_id, team_id = org.id, team.id
    context = await _org_admin_context(org_id, owner.id)

    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await org_service.enable_team_capability(
                db=session, context=context, team_id=team_id, capability="operator"
            )
    assert exc.value.status_code == 422
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_org_team_capabilities.py::test_enable_requires_active_org_capability -v`
Expected: FAIL — `enable_team_capability` does not exist.

- [ ] **Step 3: Implement the service methods**

In `service.py`:

```python
async def enable_team_capability(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
    capability: str,
) -> None:
    """Enable a marketplace capability on a team, granting it to its members.

    The org capability must already be active (the eligibility gate); otherwise
    the two-step model is violated. Owner/admin only (enforced at the router).

    Raises:
        HTTPException(404): If the team is not in this organization.
        HTTPException(422): If the org capability is not active.
    """
    org_id = context.org.id
    actor_id = context.user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam).where(OrgTeam.id == team_id, OrgTeam.org_id == org_id)
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        active = await db.scalar(
            select(1)
            .select_from(OrgCapability)
            .where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == capability,
                OrgCapability.status == "active",
            )
            .limit(1)
        )
        if active is None:
            raise HTTPException(
                status_code=422,
                detail="Activate this capability for the organization first.",
            )

        await db.execute(
            pg_insert(OrgTeamCapability)
            .values(team_id=team_id, capability=capability)
            .on_conflict_do_nothing()
        )
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_team_capability_enabled",
            target_type="organization",
            target_id=org_id,
            metadata={"team_id": str(team_id), "capability": capability},
        )
    await _sync_team_member_roles(db, team_id)


async def disable_team_capability(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
    capability: str,
) -> None:
    """Disable a capability on a team, revoking it from members who hold it only
    through this team. Owner/admin only (enforced at the router).

    Raises:
        HTTPException(404): If the team is not in this organization.
    """
    org_id = context.org.id
    actor_id = context.user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam).where(OrgTeam.id == team_id, OrgTeam.org_id == org_id)
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        row = await db.scalar(
            select(OrgTeamCapability).where(
                OrgTeamCapability.team_id == team_id,
                OrgTeamCapability.capability == capability,
            )
        )
        if row is not None:
            await db.delete(row)
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="org_team_capability_disabled",
                target_type="organization",
                target_id=org_id,
                metadata={"team_id": str(team_id), "capability": capability},
            )
    await _sync_team_member_roles(db, team_id)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/unit/modules/test_org_team_capabilities.py::test_enable_requires_active_org_capability -v`
Expected: PASS.

- [ ] **Step 5: Write + run failing test — enable grants members, disable revokes**

```python
async def test_enable_then_disable_grants_and_revokes(
    migrated_database: None, org_derived_role_state: None
) -> None:
    """Enabling grants the role to team members; disabling revokes it."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("owner")
    member = await _create_user("member")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Flow Org", slug="flow-org", country="US", created_by=owner.id
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            m = OrgMember(org_id=org.id, user_id=member.id, role="member")
            session.add(m)
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="active")
            )
            team = OrgTeam(org_id=org.id, name="Sellers")
            session.add(team)
            await session.flush()
            session.add(OrgTeamMember(team_id=team.id, member_id=m.id))
            org_id, team_id, member_user_id = org.id, team.id, member.id
    context = await _org_admin_context(org_id, owner.id)

    async with async_session_factory() as session:
        await org_service.enable_team_capability(
            db=session, context=context, team_id=team_id, capability="operator"
        )
    async with async_session_factory() as session:
        assert await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member_user_id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        ) is not None

    async with async_session_factory() as session:
        await org_service.disable_team_capability(
            db=session, context=context, team_id=team_id, capability="operator"
        )
    async with async_session_factory() as session:
        assert await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member_user_id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        ) is None
```

Run: `cd backend && uv run pytest tests/unit/modules/test_org_team_capabilities.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/organizations/service.py backend/tests/unit/modules/test_org_team_capabilities.py
git commit -m "feat(orgs): enable/disable team capability service methods"
```

---

### Task 5: Endpoints (OpenAPI-first) + integration tests

**Files:**
- Modify: `contracts/openapi.yaml` — add two paths.
- Modify: `backend/app/modules/organizations/schemas.py` — add `OrgCapabilityName` Literal.
- Modify: `backend/app/modules/organizations/router.py` — PUT/DELETE endpoints.
- Test: `backend/tests/integration/test_org_team_capability_endpoints.py` (new)

**Interfaces:**
- Consumes: `enable_team_capability`, `disable_team_capability` (Task 4), `OrgAdmin`, `DatabaseSession`.
- Produces: `PUT /v1/orgs/{org_id}/teams/{team_id}/capabilities/{capability}`, `DELETE …` — 204 on success.

- [ ] **Step 1: Add the OpenAPI paths**

In `contracts/openapi.yaml`, under the org teams paths, add:

```yaml
  /v1/orgs/{org_id}/teams/{team_id}/capabilities/{capability}:
    put:
      tags: [organizations]
      summary: Enable a capability on a team
      description: >
        Grant a marketplace capability (contributor/operator/attestor) to every
        member of a team. Requires the org capability to already be active.
        Owner/admin only.
      parameters:
        - { name: org_id, in: path, required: true, schema: { type: string, format: uuid } }
        - { name: team_id, in: path, required: true, schema: { type: string, format: uuid } }
        - name: capability
          in: path
          required: true
          schema: { type: string, enum: [contributor, operator, attestor] }
      responses:
        "204": { description: Enabled }
        "403": { description: Not an org admin }
        "404": { description: Team not found }
        "422": { description: Org capability not active }
    delete:
      tags: [organizations]
      summary: Disable a capability on a team
      description: Revoke a marketplace capability from a team. Owner/admin only.
      parameters:
        - { name: org_id, in: path, required: true, schema: { type: string, format: uuid } }
        - { name: team_id, in: path, required: true, schema: { type: string, format: uuid } }
        - name: capability
          in: path
          required: true
          schema: { type: string, enum: [contributor, operator, attestor] }
      responses:
        "204": { description: Disabled }
        "403": { description: Not an org admin }
        "404": { description: Team not found }
```

- [ ] **Step 2: Add the Literal type**

In `backend/app/modules/organizations/schemas.py` (near the top, with other type aliases; ensure `from typing import Literal` is imported):

```python
OrgCapabilityName = Literal["contributor", "operator", "attestor"]
```

- [ ] **Step 3: Write failing integration test**

Create `backend/tests/integration/test_org_team_capability_endpoints.py`, mirroring the imports/fixtures of `test_org_teams_endpoints.py` (reuse `create_org`, `create_user`, `add_member`, `auth`, `clean_orgs`, `migrated_database` from `test_organizations_endpoints`):

```python
"""Integration tests for team-capability enable/disable endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    clean_orgs,
    create_org,
    create_user,
    migrated_database,
)

pytestmark = pytest.mark.asyncio
__all__ = ["clean_orgs", "migrated_database"]


async def _create_team(client: AsyncClient, token: str, org_id: str, name: str) -> str:
    resp = await client.post(
        f"/v1/orgs/{org_id}/teams", headers=auth(token), json={"name": name}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_enable_capability_requires_active_org_capability(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """422 when enabling a capability the org has not activated."""
    del clean_orgs, migrated_database
    owner_id = await create_user("owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "cap-ep-org")
    team_id = await _create_team(client, token, str(org["id"]), "Sellers")

    resp = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/capabilities/operator",
        headers=auth(token),
    )
    assert resp.status_code == 422


async def test_enable_capability_forbidden_for_plain_member(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """A plain member cannot enable a capability on a team (403)."""
    del clean_orgs, migrated_database
    owner_id = await create_user("owner")
    member_id = await create_user("member")
    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "cap-ep-org2")
    await add_member(str(org["id"]), member_id, "member")
    team_id = await _create_team(client, owner_token, str(org["id"]), "Sellers")

    resp = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/capabilities/operator",
        headers=auth(member_token),
    )
    assert resp.status_code == 403
```

> Check whether `test_org_operator_capability_endpoints.py`'s pattern of activating a capability via `POST /operator-capability/activate` is the simplest way to make the org capability active for a positive-path test; add a positive test that activates operator, enables it on a team the member is on, and asserts the member now holds the `operator` role (query `UserRole` as in Task 2).

- [ ] **Step 4: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_org_team_capability_endpoints.py -v`
Expected: FAIL — endpoints return 404 (routes not defined).

- [ ] **Step 5: Add the router endpoints**

In `backend/app/modules/organizations/router.py`, after the team-members endpoints, add (import `OrgCapabilityName` from `.schemas`):

```python
@router.put(
    "/{org_id}/teams/{team_id}/capabilities/{capability}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Enable a capability on a team",
    description=(
        "Grant a marketplace capability to every member of a team. Requires the "
        "org capability to already be active. Owner/admin only."
    ),
)
async def enable_team_capability(
    org_id: UUID,
    team_id: UUID,
    capability: OrgCapabilityName,
    context: OrgAdmin,
    db: DatabaseSession,
) -> None:
    """Enable a capability on a team."""
    del org_id
    await service.enable_team_capability(
        db=db, context=context, team_id=team_id, capability=capability
    )


@router.delete(
    "/{org_id}/teams/{team_id}/capabilities/{capability}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disable a capability on a team",
    description="Revoke a marketplace capability from a team. Owner/admin only.",
)
async def disable_team_capability(
    org_id: UUID,
    team_id: UUID,
    capability: OrgCapabilityName,
    context: OrgAdmin,
    db: DatabaseSession,
) -> None:
    """Disable a capability on a team."""
    del org_id
    await service.disable_team_capability(
        db=db, context=context, team_id=team_id, capability=capability
    )
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_org_team_capability_endpoints.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add contracts/openapi.yaml backend/app/modules/organizations/schemas.py backend/app/modules/organizations/router.py backend/tests/integration/test_org_team_capability_endpoints.py
git commit -m "feat(orgs): team capability enable/disable endpoints"
```

---

### Task 6: Surface enabled capabilities in team reads

**Files:**
- Modify: `backend/app/modules/organizations/schemas.py:490-498` (`OrgTeamResponse`)
- Modify: `backend/app/modules/organizations/service.py` — `list_teams` (~1786), `rename_team` (~1819), `create_team` (~1747)
- Modify: `contracts/openapi.yaml` — team schema `capabilities` field
- Test: `backend/tests/integration/test_org_teams_endpoints.py`

**Interfaces:**
- Consumes: `OrgTeamCapability` (Task 1).
- Produces: `OrgTeamResponse.capabilities: list[str]`.

- [ ] **Step 1: Write failing test — list_teams returns enabled capabilities**

Add to `backend/tests/integration/test_org_teams_endpoints.py` (reuse its fixtures/helpers). The test: owner creates a team, activates operator capability for the org, enables it on the team, lists teams, asserts the team's `capabilities` contains `"operator"`.

```python
async def test_list_teams_includes_enabled_capabilities(
    client: AsyncClient, override_redis, clean_orgs: None, migrated_database: None
) -> None:
    """A team's enabled capabilities appear in the teams list response."""
    del override_redis, clean_orgs, migrated_database
    owner_id = await create_user("owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "teamcaps-org")
    # activate operator for the org (eligibility gate)
    await client.post(
        f"/v1/orgs/{org['id']}/operator-capability/activate", headers=auth(token)
    )
    team_resp = await client.post(
        f"/v1/orgs/{org['id']}/teams", headers=auth(token), json={"name": "Sellers"}
    )
    team_id = team_resp.json()["id"]
    await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/capabilities/operator",
        headers=auth(token),
    )

    listing = await client.get(f"/v1/orgs/{org['id']}/teams", headers=auth(token))
    teams = listing.json()["teams"]
    sellers = next(t for t in teams if t["id"] == team_id)
    assert sellers["capabilities"] == ["operator"]
```

> Import the `override_redis` fixture pattern if operator activation is rate-limited (mirror `test_org_operator_capability_endpoints.py`). If the teams-endpoints test file lacks it, add the same fixture.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_org_teams_endpoints.py::test_list_teams_includes_enabled_capabilities -v`
Expected: FAIL — `capabilities` key missing / KeyError.

- [ ] **Step 3: Add the schema field**

In `schemas.py`, `OrgTeamResponse`:

```python
class OrgTeamResponse(BaseModel):
    """One organization team row with member count and enabled capabilities."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    member_count: int
    capabilities: list[str] = Field(default_factory=list)
    created_at: datetime
```

Ensure `Field` is imported (it is, used elsewhere).

- [ ] **Step 4: Populate capabilities in `list_teams`**

In `service.py` `list_teams`, after building the team rows, fetch capabilities per team and attach. Replace the response construction to include a `caps_by_team` lookup:

```python
    cap_rows = await db.execute(
        select(OrgTeamCapability.team_id, OrgTeamCapability.capability)
        .join(OrgTeam, OrgTeam.id == OrgTeamCapability.team_id)
        .where(OrgTeam.org_id == org_id)
    )
    caps_by_team: dict[UUID, list[str]] = {}
    for team_id_val, cap in cap_rows:
        caps_by_team.setdefault(team_id_val, []).append(cap)

    return OrgTeamsResponse(
        teams=[
            OrgTeamResponse(
                id=row.id,
                name=row.name,
                member_count=row.member_count,
                capabilities=sorted(caps_by_team.get(row.id, [])),
                created_at=row.created_at,
            )
            for row in rows
        ]
    )
```

> Match the actual iteration variable names in the existing `list_teams` (it selects `OrgTeam.id, OrgTeam.name, OrgTeam.created_at, count(...) as member_count`). Keep `org_id = context.org.id` available.

In `rename_team`, populate capabilities for the renamed team:

```python
    caps = (
        await db.scalars(
            select(OrgTeamCapability.capability).where(
                OrgTeamCapability.team_id == team_id
            )
        )
    ).all()
    return OrgTeamResponse(
        id=team.id,
        name=team.name,
        member_count=member_count,
        capabilities=sorted(caps),
        created_at=team.created_at,
    )
```

`create_team` returns a brand-new team with no capabilities — the schema default (`[]`) covers it; leave its `OrgTeamResponse(...)` construction as is (it omits `capabilities`).

- [ ] **Step 5: Update OpenAPI team schema**

In `contracts/openapi.yaml`, add to the team response schema properties:

```yaml
        capabilities:
          type: array
          items: { type: string, enum: [contributor, operator, attestor] }
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_org_teams_endpoints.py -v`
Expected: PASS (new test + existing team tests still green).

- [ ] **Step 7: Full backend lint/type/test gate**

Run:
```
cd backend && uv run ruff check . && uv run mypy app && uv run pytest tests/unit/modules/test_org_derived_roles.py tests/unit/modules/test_org_team_capabilities.py tests/integration/test_org_team_capability_endpoints.py tests/integration/test_org_teams_endpoints.py -q
```
Expected: ruff clean, mypy clean, tests pass.

- [ ] **Step 8: Commit**

```bash
git add contracts/openapi.yaml backend/app/modules/organizations/schemas.py backend/app/modules/organizations/service.py backend/tests/integration/test_org_teams_endpoints.py
git commit -m "feat(orgs): surface enabled capabilities in team read responses"
```

---

### Task 7: Frontend — per-team capability toggles

**Files:**
- Regenerate: `frontend/src/lib/generated/*` (from updated `contracts/openapi.yaml`)
- Modify: `frontend/src/components/modules/organizations/organization-teams.tsx`
- Test: `frontend/src/components/modules/organizations/organization-teams.test.tsx` (new or extend)

**Interfaces:**
- Consumes: generated SDK `enableCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityPut` and `disableCapability…Delete` (exact names from regen); team list now returns `capabilities: string[]`.
- Produces: capability toggle UI on each team, owner/admin only.

- [ ] **Step 1: Regenerate the SDK**

Run the repo's client-gen command (check `frontend/package.json` scripts for the hey-api generate command, e.g. `npm run generate` or `npx @hey-api/openapi-ts`). Confirm the two new functions appear in `frontend/src/lib/generated/sdk.gen.ts` and `capabilities` appears on the team type in `types.gen.ts`.

Run: `cd frontend && npm run generate` (or the documented codegen script)
Expected: `sdk.gen.ts` contains the enable/disable capability functions.

- [ ] **Step 2: Write failing component test — toggle disabled when org capability inactive**

In `frontend/src/components/modules/organizations/organization-teams.test.tsx`, mock `useOrganization` (capabilities map), the toast, and `sdk.gen`. Test that for an owner, a team renders a Contributor/Operator toggle; when the org capability is not active the toggle is disabled with the hint text.

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("./organization-context", () => ({ useOrganization: vi.fn() }));
// ... mock toast, sdk.gen, form-client per the existing organization-capabilities.test.tsx pattern

it("disables the Operator toggle when the org capability is inactive", () => {
  // arrange useOrganization -> role owner, capabilities {} (operator not active)
  // render OrganizationTeams with one team that has capabilities: []
  // assert the Operator toggle is present and disabled, hint visible
});
```

> Model the mock setup on the existing `organization-capabilities.test.tsx` (hoisted spies for toast/refresh, `vi.mock("./organization-context", ...)`). Fill the assertions concretely against the rendered toggle's `aria-label` (e.g. `Enable Operator on Sellers`) and `disabled` state.

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-teams.test.tsx`
Expected: FAIL — toggle not implemented.

- [ ] **Step 4: Implement toggles in `organization-teams.tsx`**

Add, per team row, a group of capability toggles (Contributor / Operator / Attestor). Read `const { role, capabilities, refreshOrganization } = useOrganization();`. Show only for `role === "owner" || role === "admin"`. For each capability:
- Reflect current on/off from the team's `capabilities` array.
- Disabled + hint (`Activate this capability for the organization first`) when `capabilities?.[cap] !== "active"` (org capability inactive).
- On enable: open `ConfirmDialog` ("Enable {cap} on {team}? Every member of this team gains the {cap} role.") → call the enable SDK fn with `{ path: { org_id, team_id, capability }, headers: getAccessTokenHeaders() }` → on success `toast.success` + `await refreshOrganization()`.
- On disable: call the disable SDK fn (confirm optional) → refresh.
- Touch targets `min-h-11`; mobile-first layout matching the existing team card.

> Keep the file under ~200 lines; if it grows past that, extract a `TeamCapabilityToggles` subcomponent in the same directory.

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-teams.test.tsx`
Expected: PASS.

- [ ] **Step 6: Add + run the enable-calls-endpoint test**

Add a test: owner clicks Enable on a team where the org capability is active → confirm → the enable SDK fn is called once with the right path, then `refreshOrganization` is called. Run the file again; expected PASS.

- [ ] **Step 7: Frontend lint/type gate**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/components/modules/organizations/`
Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/generated frontend/src/components/modules/organizations/organization-teams.tsx frontend/src/components/modules/organizations/organization-teams.test.tsx
git commit -m "feat(orgs): per-team capability toggles in team management UI"
```

---

### Task 8: Capabilities card copy update

**Files:**
- Modify: `frontend/src/components/modules/organizations/organization-capabilities.tsx:149-151` (card subtitle) and the confirm dialog description (~line 190)
- Test: `frontend/src/components/modules/organizations/organization-capabilities.test.tsx`

**Interfaces:**
- Consumes: none new. Copy-only change.
- Produces: updated card copy explaining team-based grant.

- [ ] **Step 1: Update the card subtitle + confirm description**

Card subtitle (currently "Activate what your organization can do on the marketplace."):

```tsx
          Activate what your organization can do on the marketplace. Members
          receive each right through the teams you assign it to.
```

Confirm dialog description (currently "Every current and future member gains the {label} role…"): change to reflect eligibility + team grant:

```tsx
        description={
          pendingMeta
            ? `Unlocks the ${pendingMeta.label} capability for the organization. You then grant it to members by enabling it on their teams. Owners and admins hold it immediately.`
            : ""
        }
```

- [ ] **Step 2: Update the affected test assertion**

In `organization-capabilities.test.tsx`, the error-path test asserts the confirm title `Activate Operator capability?` — unchanged. If any test asserts the old description text, update it to the new copy. Run:

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-capabilities.test.tsx`
Expected: PASS.

- [ ] **Step 3: Frontend lint/type**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/components/modules/organizations/organization-capabilities.tsx`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/modules/organizations/organization-capabilities.tsx frontend/src/components/modules/organizations/organization-capabilities.test.tsx
git commit -m "feat(orgs): clarify capabilities card copy for team-based grants"
```

---

## Final Verification

- [ ] Backend full gate: `cd backend && uv run ruff check . && uv run mypy app && uv run pytest -q`
- [ ] Migration round-trip: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
- [ ] Frontend gate: `cd frontend && npx tsc --noEmit && npx eslint . && npx vitest run`
- [ ] Manual smoke (running app): activate a capability → assign it to a team → add a member to that team → confirm the member gains the tab/pill; remove them → confirm it disappears.
- [ ] Attestor audit: confirm the "All members" backfill covered active attestor so existing reviewing-members kept access; confirm a fresh attestor approval + team assignment grants a plain member the attestor role.
```
