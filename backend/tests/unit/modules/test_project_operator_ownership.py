"""Unit tests for Project operator XOR ownership and org Project posting.

Covers the operator XOR CHECK constraint, the operator-resolution helper, org
Project creation stamping, the org-level self-deal bid guard, and regression of
the existing individual create + member-level conflict-of-interest guard.

Maps to: Task 6 in docs/superpowers/specs/2026-07-10-org-operator-design.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.modules.projects import service as project_service
from app.modules.projects.models import Project, Proposal
from app.modules.projects.operator_ownership import (
    ProjectOperator,
    resolve_project_operator,
)
from app.modules.projects.schemas import DeliverableSpec, ProjectCreateRequest
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for operator ownership tests."""
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    yield


@pytest.fixture
async def operator_ownership_state() -> AsyncIterator[None]:
    """Reset Project and org rows around each operator ownership test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete Project and org-linked rows in dependency order."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Proposal))
            await session.execute(delete(Project))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str) -> User:
    """Create and return one verified user."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            await session.refresh(user)
            return user


async def _create_org(
    owner: User,
    *,
    name: str = "Operator Org",
    operator_active: bool = False,
    contributor_active: bool = False,
) -> Organization:
    """Create an organization with the owner and optional active capabilities."""
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                slug=f"org-{uuid4().hex[:6]}",
                name=name,
                country="GB",
                created_by=owner.id,
            )
            session.add(organization)
            await session.flush()
            session.add(
                OrgMember(org_id=organization.id, user_id=owner.id, role="owner")
            )
            if operator_active:
                session.add(
                    OrgCapability(
                        org_id=organization.id,
                        capability="operator",
                        status="active",
                    )
                )
            if contributor_active:
                session.add(
                    OrgCapability(
                        org_id=organization.id,
                        capability="contributor",
                        status="active",
                    )
                )
            await session.refresh(organization)
            return organization


async def _add_member(org: Organization, user: User, role: str = "member") -> OrgMember:
    """Add a member row to an organization and return it."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org.id, user_id=user.id, role=role)
            session.add(member)
            await session.flush()
            await session.refresh(member)
            return member


async def _member_of(org: Organization, user: User) -> OrgMember:
    """Return an existing membership row for a user in an organization."""
    async with async_session_factory() as session:
        member = await session.scalar(
            select(OrgMember).where(
                OrgMember.org_id == org.id,
                OrgMember.user_id == user.id,
            )
        )
        assert member is not None
        return member


def _payload(title: str = "Procurement Playbook") -> ProjectCreateRequest:
    """Return a valid Project create request."""
    return ProjectCreateRequest(
        title=title,
        description="Build a procurement operating model for the org.",
        category="operations",
        required_deliverables=[
            DeliverableSpec(name="Playbook", description="Implementation guide")
        ],
        budget_min=Decimal("1000.00"),
        budget_max=Decimal("2000.00"),
        currency="USD",
    )


async def test_operator_xor_rejects_both_set_and_neither(
    migrated_database: None,
    operator_ownership_state: None,
) -> None:
    """The operator XOR CHECK rejects rows with both or neither operator set."""
    del migrated_database, operator_ownership_state
    owner = await _create_user("xor-owner")
    org = await _create_org(owner)

    def _row(**operator_fields: object) -> Project:
        return Project(
            title="XOR",
            description="XOR constraint probe project.",
            category="ops",
            required_deliverables=[{"name": "n", "description": "d"}],
            budget_min=Decimal("10.00"),
            budget_max=Decimal("20.00"),
            expires_at=datetime.now(UTC) + timedelta(days=30),
            **operator_fields,
        )

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(_row(operator_id=owner.id, operator_org_id=org.id))

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(_row())


def test_resolve_project_operator_distinguishes_user_and_org() -> None:
    """resolve_project_operator returns the correct branch for each ownership."""
    user_id = uuid4()
    org_id = uuid4()

    user_project = Project(operator_id=user_id, operator_org_id=None)
    org_project = Project(operator_id=None, operator_org_id=org_id)

    assert resolve_project_operator(user_project) == ProjectOperator(
        kind="user", user_id=user_id, org_id=None
    )
    assert resolve_project_operator(org_project) == ProjectOperator(
        kind="org", user_id=None, org_id=org_id
    )


async def test_create_org_project_stamps_org_and_posting_member(
    migrated_database: None,
    operator_ownership_state: None,
) -> None:
    """Org Project creation stamps org + posting member and leaves operator NULL."""
    del migrated_database, operator_ownership_state
    owner = await _create_user("org-op-owner")
    org = await _create_org(owner, operator_active=True)
    owner_member = await _member_of(org, owner)

    async with async_session_factory() as session:
        response = await project_service.create_org_project(
            db=session,
            org_id=org.id,
            actor=owner,
            posting_member_id=owner_member.id,
            payload=_payload(),
        )

    assert response.operator_id is None
    assert response.operator_org_id == org.id
    assert response.operator_name == org.name
    # Provenance stays server-side only.
    assert "posting_member_id" not in response.model_dump()

    async with async_session_factory() as session:
        stored = await session.scalar(select(Project).where(Project.id == response.id))
    assert stored is not None
    assert stored.operator_id is None
    assert stored.operator_org_id == org.id
    assert stored.posting_member_id == owner_member.id


async def test_create_org_project_requires_active_operator_capability(
    migrated_database: None,
    operator_ownership_state: None,
) -> None:
    """Org Project creation is refused when the operator capability is inactive."""
    del migrated_database, operator_ownership_state
    owner = await _create_user("org-op-owner")
    org = await _create_org(owner, operator_active=False)
    owner_member = await _member_of(org, owner)

    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await project_service.create_org_project(
                db=session,
                org_id=org.id,
                actor=owner,
                posting_member_id=owner_member.id,
                payload=_payload(),
            )
    assert getattr(exc_info.value, "status_code", None) == 403


async def test_individual_create_project_regression(
    migrated_database: None,
    operator_ownership_state: None,
) -> None:
    """Individual Project creation still stamps operator_id and leaves org NULL."""
    del migrated_database, operator_ownership_state
    operator = await _create_user("individual-operator")

    async with async_session_factory() as session:
        project = await project_service.create_project(
            db=session,
            operator=operator,
            payload=_payload(),
        )

    assert project.operator_id == operator.id
    assert project.operator_org_id is None
    assert project.posting_member_id is None


async def test_list_projects_open_feed_resolves_org_operated_project(
    migrated_database: None,
    operator_ownership_state: None,
) -> None:
    """The Contributor open feed lists an org-operated Project without raising."""
    del migrated_database, operator_ownership_state
    owner = await _create_user("org-op-owner")
    contributor = await _create_user("browsing-contributor")
    org = await _create_org(owner, name="Feed Org", operator_active=True)
    owner_member = await _member_of(org, owner)

    async with async_session_factory() as session:
        await project_service.create_org_project(
            db=session,
            org_id=org.id,
            actor=owner,
            posting_member_id=owner_member.id,
            payload=_payload(),
        )

    async with async_session_factory() as session:
        feed = await project_service.list_projects(
            db=session,
            user=contributor,
            role="contributor",
            token_roles=["contributor"],
            page=1,
            page_size=20,
            scope="open",
        )

    assert feed.total == 1
    listed = feed.projects[0]
    assert listed.operator_id is None
    assert listed.operator_org_id == org.id
    assert listed.operator_name == "Feed Org"


async def test_org_bid_on_own_operator_project_is_self_deal(
    migrated_database: None,
    operator_ownership_state: None,
) -> None:
    """An org bidding on its own operated Project is rejected as a self-deal."""
    del migrated_database, operator_ownership_state
    owner = await _create_user("dual-owner")
    delivery = await _create_user("dual-delivery")
    org = await _create_org(
        owner,
        name="Dual Org",
        operator_active=True,
        contributor_active=True,
    )
    owner_member = await _member_of(org, owner)
    delivery_member = await _add_member(org, delivery, role="member")

    async with async_session_factory() as session:
        project = await project_service.create_org_project(
            db=session,
            org_id=org.id,
            actor=owner,
            posting_member_id=owner_member.id,
            payload=_payload(),
        )

    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await project_service.submit_org_proposal(
                db=session,
                org_id=org.id,
                actor_id=owner.id,
                project_id=project.id,
                delivering_member_id=delivery_member.id,
                scope="We will deliver the procurement operating model in full.",
                budget=Decimal("1500.00"),
                timeline_days=21,
                deliverables=[{"name": "Model", "description": "Documented model"}],
            )
    assert getattr(exc_info.value, "status_code", None) == 422
    assert exc_info.value.detail == {"error_code": "self_deal_conflict"}


async def test_member_level_conflict_of_interest_regression(
    migrated_database: None,
    operator_ownership_state: None,
) -> None:
    """The individual Operator being an org member still blocks the org bid."""
    del migrated_database, operator_ownership_state
    operator = await _create_user("member-operator")
    owner = await _create_user("coi-owner")
    delivery = await _create_user("coi-delivery")
    org = await _create_org(owner, name="COI Org", contributor_active=True)
    # The individual Project Operator is also a member of the bidding org.
    await _add_member(org, operator, role="member")
    delivery_member = await _add_member(org, delivery, role="member")

    async with async_session_factory() as session:
        project = await project_service.create_project(
            db=session,
            operator=operator,
            payload=_payload(),
        )

    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await project_service.submit_org_proposal(
                db=session,
                org_id=org.id,
                actor_id=owner.id,
                project_id=project.id,
                delivering_member_id=delivery_member.id,
                scope="We will deliver the procurement operating model in full.",
                budget=Decimal("1500.00"),
                timeline_days=21,
                deliverables=[{"name": "Model", "description": "Documented model"}],
            )
    assert getattr(exc_info.value, "status_code", None) == 422
    assert exc_info.value.detail == {"error_code": "self_deal_conflict"}
