"""Integration tests for Phase 4a Project CRUD and proposal flow."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.projects.models import Project, Proposal
from app.shared.models.audit_log import AuditLog


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Project tables exist for endpoint tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def project_context() -> AsyncIterator[dict[str, Any]]:
    """Reset Project, proposal, audit, and auth rows between tests."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete project rows in dependency order."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Project))
            await session.execute(delete(Proposal))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield {}
    finally:
        await cleanup()
        await engine.dispose()


async def create_user(
    email: str,
    roles: list[str],
    *,
    kyc_status: str = "verified",
) -> UUID:
    """Create a verified user with approved roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status=kyc_status,
            )
            session.add(user)
            await session.flush()
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


def project_payload() -> dict[str, Any]:
    """Return a valid Project create payload."""
    return {
        "title": "Procurement Playbook",
        "description": "Build a procurement operating model.",
        "category": "operations",
        "required_deliverables": [
            {"name": "Playbook", "description": "Implementation guide"}
        ],
        "budget_min": "1000.00",
        "budget_max": "2000.00",
        "currency": "USD",
        "deadline": date(2026, 8, 1).isoformat(),
    }


def proposal_payload() -> dict[str, Any]:
    """Return a valid Proposal submit payload."""
    return {
        "scope": "I will deliver the procurement model and rollout plan.",
        "budget": "1500.00",
        "currency": "USD",
        "timeline_days": 21,
        "deliverables": [
            {"name": "Operating model", "description": "Documented model"}
        ],
    }


async def test_operator_creates_project_contributor_proposes_and_operator_accepts(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """The core Project marketplace flow creates, bids, and assigns work."""
    operator_id = await create_user("project-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "project-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])

    created = await client.post(
        "/v1/projects",
        headers=operator_headers,
        json=project_payload(),
    )
    project_id = created.json()["id"]
    feed = await client.get(
        "/v1/projects",
        params={"role": "contributor"},
        headers=contributor_headers,
    )
    proposed = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=contributor_headers,
        json=proposal_payload(),
    )
    proposal_id = proposed.json()["id"]
    accepted = await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/accept",
        headers=operator_headers,
    )

    async with async_session_factory() as session:
        project = await session.scalar(select(Project).where(Project.id == project_id))
        proposal = await session.scalar(
            select(Proposal).where(Proposal.id == proposal_id)
        )

    assert created.status_code == 201
    assert created.json()["status"] == "open"
    assert feed.status_code == 200
    assert [item["id"] for item in feed.json()["projects"]] == [project_id]
    assert proposed.status_code == 201
    assert proposed.json()["status"] == "pending"
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "assigned"
    assert accepted.json()["accepted_proposal_id"] == proposal_id
    assert project is not None
    assert project.status == "assigned"
    assert project.accepted_proposal_id == UUID(proposal_id)
    assert proposal is not None
    assert proposal.status == "accepted"


async def test_project_create_requires_kyc_and_enforces_active_cap(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Operators need KYC and cannot exceed five active MVP Projects."""
    pending_operator = await create_user(
        "project-pending@auracles.space",
        ["operator"],
        kyc_status="pending",
    )
    verified_operator = await create_user("project-cap@auracles.space", ["operator"])

    kyc_blocked = await client.post(
        "/v1/projects",
        headers=auth_headers(pending_operator, ["operator"]),
        json=project_payload(),
    )
    for index in range(5):
        payload = project_payload()
        payload["title"] = f"Project {index}"
        response = await client.post(
            "/v1/projects",
            headers=auth_headers(verified_operator, ["operator"]),
            json=payload,
        )
        assert response.status_code == 201
    cap_blocked = await client.post(
        "/v1/projects",
        headers=auth_headers(verified_operator, ["operator"]),
        json=project_payload(),
    )

    assert kyc_blocked.status_code == 403
    assert cap_blocked.status_code == 409
    assert "maximum" in cap_blocked.json()["detail"].lower()
