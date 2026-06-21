"""Integration tests for Phase 4a Project CRUD and proposal flow."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, func, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, Transaction
from app.modules.frameworks.models import Framework
from app.modules.projects import dispute_service, milestone_service
from app.modules.projects.models import (
    Deliverable,
    Dispute,
    Milestone,
    Project,
    Proposal,
    ProposalAmendment,
)
from app.modules.workspace import service as workspace_service
from app.modules.workspace.models import WorkspaceMessage, WorkspaceUploadSession
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async


class FakeStripeCustomer:
    """Small stand-in for a Stripe Customer result in Project payment tests."""

    def __init__(self, customer_id: str) -> None:
        """Store the provider customer id."""
        self.id = customer_id


class FakeStripePaymentIntent:
    """Small stand-in for a Stripe PaymentIntent result."""

    def __init__(self, payment_intent_id: str, client_secret: str) -> None:
        """Store the provider intent id and browser client secret."""
        self.id = payment_intent_id
        self.client_secret = client_secret


class FakeRedis:
    """Redis test double for TOTP-sensitive Project admin routes."""

    def __init__(self) -> None:
        """Create empty in-memory Redis state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored value or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for a key."""
        self.ttls[key] = seconds

    async def delete(self, *keys: str) -> int:
        """Delete stored values and counters."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
        return removed


class FakeStripeRefund:
    """Small stand-in for a Stripe refund result."""

    def __init__(self, refund_id: str) -> None:
        """Store the provider refund id and status."""
        self.id = refund_id
        self.status = "succeeded"


class FakeNotificationTask:
    """Small stand-in for Celery notification dispatch."""

    def __init__(self, calls: list[dict[str, Any]]) -> None:
        """Store a mutable call list for assertions."""
        self.calls = calls

    def delay(self, **kwargs: Any) -> None:
        """Record notification dispatch requests without using Redis."""
        self.calls.append(kwargs)


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
            await session.execute(delete(WorkspaceMessage))
            await session.execute(delete(WorkspaceUploadSession))
            await session.execute(delete(Dispute))
            await session.execute(delete(Deliverable))
            await session.execute(delete(Milestone))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(ProposalAmendment))
            await session.execute(delete(Framework))
            await session.execute(delete(Project))
            await session.execute(delete(Proposal))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield {}
    finally:
        await cleanup()
        await engine.dispose()


async def create_admin_user() -> tuple[UUID, str]:
    """Create a TOTP-enabled Admin user for Project dispute resolution tests."""
    secret = pyotp.random_base32()
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email="project-dispute-admin@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Project Dispute Admin",
                email_verified=True,
                kyc_status="verified",
                totp_enabled=True,
                totp_secret=encrypt_totp_secret(secret),
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id,
                    role="admin",
                    approved_at=datetime.now(UTC),
                )
            )
        return user.id, secret


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


async def test_contributor_assigned_scope_lists_accepted_project(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """A Contributor's accepted Project appears under scope=assigned, not scope=open.

    Regression: list_projects(role=contributor) returned only status=='open'
    Projects, so an accepted Contributor lost all navigation to their assigned
    Project once acceptance moved it out of the open feed.
    """
    operator_id = await create_user("assign-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "assign-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])

    project_id = (
        await client.post(
            "/v1/projects",
            headers=operator_headers,
            json=project_payload(),
        )
    ).json()["id"]
    proposal_id = (
        await client.post(
            f"/v1/projects/{project_id}/proposals",
            headers=contributor_headers,
            json=proposal_payload(),
        )
    ).json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/accept",
        headers=operator_headers,
    )

    assigned = await client.get(
        "/v1/projects",
        params={"role": "contributor", "scope": "assigned"},
        headers=contributor_headers,
    )
    open_feed = await client.get(
        "/v1/projects",
        params={"role": "contributor", "scope": "open"},
        headers=contributor_headers,
    )

    assert assigned.status_code == 200
    assert [item["id"] for item in assigned.json()["projects"]] == [project_id]
    assert open_feed.status_code == 200
    assert project_id not in [item["id"] for item in open_feed.json()["projects"]]


async def test_contributor_assigned_scope_excludes_pending_proposal(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """A merely-pending Proposal does not surface the Project under scope=assigned.

    Only an accepted Proposal counts as an assignment; otherwise an open feed of
    every Project a Contributor bid on would leak through the assigned scope.
    """
    operator_id = await create_user("pending-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "pending-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])

    project_id = (
        await client.post(
            "/v1/projects",
            headers=operator_headers,
            json=project_payload(),
        )
    ).json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=contributor_headers,
        json=proposal_payload(),
    )

    assigned = await client.get(
        "/v1/projects",
        params={"role": "contributor", "scope": "assigned"},
        headers=contributor_headers,
    )

    assert assigned.status_code == 200
    assert project_id not in [item["id"] for item in assigned.json()["projects"]]


async def test_project_create_rejects_past_deadline(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Project creation must reject deadlines earlier than today."""
    operator_id = await create_user("project-deadline@auracles.space", ["operator"])
    payload = project_payload()
    payload["deadline"] = date.fromordinal(date.today().toordinal() - 1).isoformat()

    response = await client.post(
        "/v1/projects",
        headers=auth_headers(operator_id, ["operator"]),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == (
        "Value error, deadline cannot be in the past."
    )


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


async def test_project_member_proposes_and_counterparty_accepts_amendment(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Accepted Project members can amend budget only with counterparty consent."""
    operator_id = await create_user("amend-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "amend-contributor@auracles.space",
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
    proposed = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=contributor_headers,
        json=proposal_payload(),
    )
    proposal_id = proposed.json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/accept",
        headers=operator_headers,
    )
    async with async_session_factory() as session:
        project = await session.scalar(select(Project).where(Project.id == project_id))
        assert project is not None
        project.milestone_plan_status = "finalized"
        await session.commit()

    amendment = await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/amendments",
        headers=contributor_headers,
        json={
            "change_type": "budget",
            "after": {"budget": "1750.00"},
            "reason": "Scope needs deeper implementation support.",
        },
    )
    amendment_id = amendment.json()["id"]
    proposer_accept = await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/amendments/"
        f"{amendment_id}/accept",
        headers=contributor_headers,
    )
    accepted = await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/amendments/"
        f"{amendment_id}/accept",
        headers=operator_headers,
    )

    async with async_session_factory() as session:
        proposal = await session.scalar(
            select(Proposal).where(Proposal.id == proposal_id)
        )
        project = await session.scalar(select(Project).where(Project.id == project_id))
        messages = (
            (
                await session.execute(
                    select(WorkspaceMessage)
                    .where(WorkspaceMessage.project_id == UUID(project_id))
                    .order_by(WorkspaceMessage.created_at)
                )
            )
            .scalars()
            .all()
        )

    assert amendment.status_code == 201
    assert amendment.json()["status"] == "pending"
    assert amendment.json()["before"]["budget"] == "1500.00"
    assert amendment.json()["after"]["budget"] == "1750.00"
    assert proposer_accept.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert proposal is not None
    assert str(proposal.budget) == "1750.00"
    assert project is not None
    assert project.milestone_plan_status == "draft"
    assert [message.system_event for message in messages] == [
        "amendment_proposed",
        "amendment_accepted",
    ]


async def test_accepted_contributor_manages_draft_milestones_and_finalizes_plan(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Accepted Contributor can draft milestones; exact budget sum finalizes."""
    operator_id = await create_user("milestone-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "milestone-contributor@auracles.space",
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
    proposed = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=contributor_headers,
        json=proposal_payload(),
    )
    proposal_id = proposed.json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/accept",
        headers=operator_headers,
    )

    first = await client.post(
        f"/v1/projects/{project_id}/milestones",
        headers=contributor_headers,
        json={
            "sequence": 1,
            "name": "Discovery",
            "description": "Map current procurement workflows.",
            "budget": "1000.00",
            "currency": "USD",
        },
    )
    first_id = first.json()["id"]
    listed = await client.get(
        f"/v1/projects/{project_id}/milestones",
        headers=operator_headers,
    )
    finalize_too_low = await client.post(
        f"/v1/projects/{project_id}/milestones/finalize",
        headers=contributor_headers,
    )
    second = await client.post(
        f"/v1/projects/{project_id}/milestones",
        headers=contributor_headers,
        json={
            "sequence": 2,
            "name": "Temporary",
            "description": "A milestone we will remove before finalizing.",
            "budget": "100.00",
            "currency": "USD",
        },
    )
    deleted = await client.delete(
        f"/v1/projects/{project_id}/milestones/{second.json()['id']}",
        headers=contributor_headers,
    )
    updated = await client.patch(
        f"/v1/projects/{project_id}/milestones/{first_id}",
        headers=contributor_headers,
        json={"budget": "1500.00"},
    )
    finalized = await client.post(
        f"/v1/projects/{project_id}/milestones/finalize",
        headers=contributor_headers,
    )
    edit_after_finalize = await client.patch(
        f"/v1/projects/{project_id}/milestones/{first_id}",
        headers=contributor_headers,
        json={"name": "Locked"},
    )

    async with async_session_factory() as session:
        project = await session.scalar(select(Project).where(Project.id == project_id))
        milestones = (
            (
                await session.execute(
                    select(Milestone)
                    .where(Milestone.project_id == UUID(project_id))
                    .order_by(Milestone.sequence)
                )
            )
            .scalars()
            .all()
        )

    assert first.status_code == 201
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()["milestones"]] == ["Discovery"]
    assert finalize_too_low.status_code == 422
    assert second.status_code == 201
    assert deleted.status_code == 204
    assert updated.status_code == 200
    assert updated.json()["budget"] == "1500.00"
    assert finalized.status_code == 200
    assert finalized.json()["milestone_plan_status"] == "finalized"
    assert edit_after_finalize.status_code == 409
    assert project is not None
    assert project.milestone_plan_status == "finalized"
    assert len(milestones) == 1
    assert milestones[0].sequence == 1
    assert str(milestones[0].budget) == "1500.00"


async def _accept_project_for_milestones(
    client: AsyncClient,
    operator_headers: Mapping[str, str],
    contributor_headers: Mapping[str, str],
) -> str:
    """Create an Operator Project and accept the Contributor Proposal.

    Returns the project id with an accepted Proposal of budget 1500.00 (from
    ``proposal_payload``), ready for draft milestone management.
    """
    project_id = (
        await client.post(
            "/v1/projects",
            headers=operator_headers,
            json=project_payload(),
        )
    ).json()["id"]
    proposal_id = (
        await client.post(
            f"/v1/projects/{project_id}/proposals",
            headers=contributor_headers,
            json=proposal_payload(),
        )
    ).json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/accept",
        headers=operator_headers,
    )
    return project_id


async def test_create_milestone_rejects_total_over_proposal_budget(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Adding a Milestone may not push the budget total over the Proposal budget.

    The accepted Proposal budget is 1500.00; a running total that would exceed it
    is rejected, while a total equal to it is allowed.
    """
    operator_id = await create_user("over-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "over-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id = await _accept_project_for_milestones(
        client, operator_headers, contributor_headers
    )

    first = await client.post(
        f"/v1/projects/{project_id}/milestones",
        headers=contributor_headers,
        json={
            "sequence": 1,
            "name": "Discovery",
            "description": "Map current procurement workflows.",
            "budget": "1000.00",
            "currency": "USD",
        },
    )
    over = await client.post(
        f"/v1/projects/{project_id}/milestones",
        headers=contributor_headers,
        json={
            "sequence": 2,
            "name": "Too much",
            "description": "This would push the total to 1600.",
            "budget": "600.00",
            "currency": "USD",
        },
    )
    at_limit = await client.post(
        f"/v1/projects/{project_id}/milestones",
        headers=contributor_headers,
        json={
            "sequence": 3,
            "name": "Exact remainder",
            "description": "Brings the total to exactly 1500.",
            "budget": "500.00",
            "currency": "USD",
        },
    )

    assert first.status_code == 201
    assert over.status_code == 422
    assert at_limit.status_code == 201


async def test_update_milestone_rejects_total_over_proposal_budget(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Raising a Milestone budget may not push the plan total over the Proposal.

    With two Milestones summing to exactly 1500.00, raising one rejects, while a
    change that keeps the total within 1500.00 is allowed.
    """
    operator_id = await create_user("upd-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "upd-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id = await _accept_project_for_milestones(
        client, operator_headers, contributor_headers
    )

    first_id = (
        await client.post(
            f"/v1/projects/{project_id}/milestones",
            headers=contributor_headers,
            json={
                "sequence": 1,
                "name": "Discovery",
                "description": "Map current procurement workflows.",
                "budget": "1000.00",
                "currency": "USD",
            },
        )
    ).json()["id"]
    second_id = (
        await client.post(
            f"/v1/projects/{project_id}/milestones",
            headers=contributor_headers,
            json={
                "sequence": 2,
                "name": "Delivery",
                "description": "Deliver the playbook.",
                "budget": "500.00",
                "currency": "USD",
            },
        )
    ).json()["id"]

    over = await client.patch(
        f"/v1/projects/{project_id}/milestones/{second_id}",
        headers=contributor_headers,
        json={"budget": "600.00"},
    )
    within = await client.patch(
        f"/v1/projects/{project_id}/milestones/{first_id}",
        headers=contributor_headers,
        json={"budget": "900.00"},
    )

    assert over.status_code == 422
    assert within.status_code == 200


async def _finalize_single_milestone_plan(
    client: AsyncClient,
    project_id: str,
    contributor_headers: Mapping[str, str],
) -> str:
    """Create one Milestone equal to the Proposal budget and finalize the plan.

    Returns the milestone id; the plan ends ``finalized``.
    """
    milestone_id = (
        await client.post(
            f"/v1/projects/{project_id}/milestones",
            headers=contributor_headers,
            json={
                "sequence": 1,
                "name": "Whole engagement",
                "description": "Single milestone covering the full budget.",
                "budget": "1500.00",
                "currency": "USD",
            },
        )
    ).json()["id"]
    finalized = await client.post(
        f"/v1/projects/{project_id}/milestones/finalize",
        headers=contributor_headers,
    )
    assert finalized.status_code == 200
    assert finalized.json()["milestone_plan_status"] == "finalized"
    return milestone_id


async def test_reopen_milestone_plan_while_unfunded_returns_to_draft(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Either member may reopen a finalized plan to draft while nothing is funded.

    Reopening flips the plan back to ``draft`` and re-enables milestone edits.
    """
    operator_id = await create_user("reopen-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "reopen-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id = await _accept_project_for_milestones(
        client, operator_headers, contributor_headers
    )
    await _finalize_single_milestone_plan(client, project_id, contributor_headers)

    reopened = await client.post(
        f"/v1/projects/{project_id}/milestones/reopen",
        headers=operator_headers,
    )
    edit_after_reopen = await client.patch(
        f"/v1/projects/{project_id}/milestones/"
        f"{(await client.get(f'/v1/projects/{project_id}/milestones', headers=contributor_headers)).json()['milestones'][0]['id']}",
        headers=contributor_headers,
        json={"budget": "1200.00"},
    )

    assert reopened.status_code == 200
    assert reopened.json()["milestone_plan_status"] == "draft"
    assert edit_after_reopen.status_code == 200


async def test_reopen_milestone_plan_blocked_after_funding(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """A plan may not be reopened once any Milestone has been funded."""
    operator_id = await create_user("nofund-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "nofund-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id = await _accept_project_for_milestones(
        client, operator_headers, contributor_headers
    )
    milestone_id = await _finalize_single_milestone_plan(
        client, project_id, contributor_headers
    )

    async with async_session_factory() as session:
        async with session.begin():
            milestone = await session.scalar(
                select(Milestone).where(Milestone.id == milestone_id)
            )
            milestone.status = "funded"

    blocked = await client.post(
        f"/v1/projects/{project_id}/milestones/reopen",
        headers=operator_headers,
    )

    assert blocked.status_code == 409


async def test_operator_cancels_acceptance_reopens_project_and_clears_plan(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Operator cancels an unfunded acceptance: Project reopens, plan cleared.

    The Proposal is marked rejected, the Project returns to ``open`` with no
    accepted Proposal, and the Contributor's draft Milestones are removed.
    """
    operator_id = await create_user("cancel-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "cancel-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id = await _accept_project_for_milestones(
        client, operator_headers, contributor_headers
    )
    await client.post(
        f"/v1/projects/{project_id}/milestones",
        headers=contributor_headers,
        json={
            "sequence": 1,
            "name": "Discovery",
            "description": "Draft milestone that should be cleared on cancel.",
            "budget": "500.00",
            "currency": "USD",
        },
    )

    cancelled = await client.post(
        f"/v1/projects/{project_id}/cancel-acceptance",
        headers=operator_headers,
    )

    async with async_session_factory() as session:
        project = await session.scalar(select(Project).where(Project.id == project_id))
        proposal = await session.scalar(
            select(Proposal).where(Proposal.project_id == project_id)
        )
        remaining = (
            await session.execute(
                select(Milestone).where(Milestone.project_id == project_id)
            )
        ).scalars().all()

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "open"
    assert cancelled.json()["accepted_proposal_id"] is None
    assert project is not None
    assert project.status == "open"
    assert project.accepted_proposal_id is None
    assert proposal is not None
    assert proposal.status == "rejected"
    assert remaining == []


async def test_contributor_cancels_acceptance_marks_proposal_withdrawn(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """A Contributor backing out of an unfunded acceptance withdraws the Proposal."""
    operator_id = await create_user("cback-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "cback-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id = await _accept_project_for_milestones(
        client, operator_headers, contributor_headers
    )

    cancelled = await client.post(
        f"/v1/projects/{project_id}/cancel-acceptance",
        headers=contributor_headers,
    )

    async with async_session_factory() as session:
        proposal = await session.scalar(
            select(Proposal).where(Proposal.project_id == project_id)
        )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "open"
    assert proposal is not None
    assert proposal.status == "withdrawn"


async def test_cancel_acceptance_blocked_after_funding(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Acceptance cannot be cancelled once a Milestone is funded (use disputes)."""
    operator_id = await create_user("cblock-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "cblock-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id = await _accept_project_for_milestones(
        client, operator_headers, contributor_headers
    )
    milestone_id = await _finalize_single_milestone_plan(
        client, project_id, contributor_headers
    )

    async with async_session_factory() as session:
        async with session.begin():
            project = await session.scalar(
                select(Project).where(Project.id == project_id)
            )
            project.status = "in_progress"
            milestone = await session.scalar(
                select(Milestone).where(Milestone.id == milestone_id)
            )
            milestone.status = "funded"

    blocked = await client.post(
        f"/v1/projects/{project_id}/cancel-acceptance",
        headers=operator_headers,
    )

    assert blocked.status_code == 409


async def test_contributor_can_rebid_after_cancelled_acceptance(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """A cancelled acceptance leaves the Contributor free to submit a new Proposal.

    The reopened Project accepts a fresh bid because the prior Proposal is no
    longer in an active (pending/accepted) state.
    """
    operator_id = await create_user("rebid-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "rebid-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id = await _accept_project_for_milestones(
        client, operator_headers, contributor_headers
    )
    await client.post(
        f"/v1/projects/{project_id}/cancel-acceptance",
        headers=operator_headers,
    )

    rebid = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=contributor_headers,
        json=proposal_payload(),
    )

    assert rebid.status_code == 201
    assert rebid.json()["status"] == "pending"


async def test_project_listings_include_operator_name(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Project listings carry the posting Operator's display name for cards."""
    operator_id = await create_user("poster-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "feed-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])

    await client.post(
        "/v1/projects",
        headers=operator_headers,
        json=project_payload(),
    )

    operator_view = await client.get(
        "/v1/projects",
        params={"role": "operator"},
        headers=operator_headers,
    )
    open_feed = await client.get(
        "/v1/projects",
        params={"role": "contributor", "scope": "open"},
        headers=contributor_headers,
    )

    assert operator_view.status_code == 200
    assert operator_view.json()["projects"][0]["operator_name"] == "poster-operator"
    assert open_feed.status_code == 200
    assert open_feed.json()["projects"][0]["operator_name"] == "poster-operator"


async def test_proposal_listings_include_proposer_name(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Proposal listings expose the proposer's display name to both sides.

    The Operator's view of bids and the Contributor's own list both carry
    ``contributor_name`` so the UI can label who proposed.
    """
    operator_id = await create_user("names-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "names-bidder@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])

    project_id = (
        await client.post(
            "/v1/projects",
            headers=operator_headers,
            json=project_payload(),
        )
    ).json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=contributor_headers,
        json=proposal_payload(),
    )

    operator_view = await client.get(
        f"/v1/projects/{project_id}/proposals",
        headers=operator_headers,
    )
    contributor_view = await client.get(
        f"/v1/projects/{project_id}/proposals/mine",
        headers=contributor_headers,
    )

    assert operator_view.status_code == 200
    assert operator_view.json()["proposals"][0]["contributor_name"] == "names-bidder"
    assert contributor_view.status_code == 200
    assert (
        contributor_view.json()["proposals"][0]["contributor_name"] == "names-bidder"
    )


async def test_workspace_upload_session_rejects_disallowed_file_type(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Deliverable/workspace uploads enforce a content-type allowlist.

    Dangerous, inline-renderable types (HTML) are rejected with 415; document
    types used for Deliverables are allowed.
    """
    operator_id = await create_user("upmime-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "upmime-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id = await _accept_project_for_milestones(
        client, operator_headers, contributor_headers
    )

    rejected = await client.post(
        f"/v1/projects/{project_id}/messages/uploads",
        headers=contributor_headers,
        json={
            "file_name": "evil.html",
            "content_type": "text/html",
            "size_bytes": 1024,
        },
    )
    allowed = await client.post(
        f"/v1/projects/{project_id}/messages/uploads",
        headers=contributor_headers,
        json={
            "file_name": "report.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1024,
        },
    )

    assert rejected.status_code == 415
    assert allowed.status_code == 201


async def test_operator_funds_finalized_pending_milestone_with_stripe_intent(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Funding creates a pending escrow transaction; webhook funds Milestone later."""
    calls: dict[str, list[Any]] = {"customers": [], "payment_intents": []}

    async def fake_create_customer(
        *,
        email: str,
        name: str | None = None,
        idempotency_key: str | None = None,
    ) -> FakeStripeCustomer:
        """Record Stripe Customer creation and return a stable id."""
        calls["customers"].append(
            {"email": email, "name": name, "idempotency_key": idempotency_key}
        )
        return FakeStripeCustomer("cus_project_123")

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: Mapping[str, str],
        idempotency_key: str | None = None,
    ) -> FakeStripePaymentIntent:
        """Record Stripe PaymentIntent creation for milestone funding."""
        calls["payment_intents"].append(
            {
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency,
                "metadata": dict(metadata),
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripePaymentIntent("pi_milestone_123", "pi_milestone_secret")

    monkeypatch.setattr(
        milestone_service.stripe,
        "create_customer",
        fake_create_customer,
    )
    monkeypatch.setattr(
        milestone_service.stripe,
        "create_payment_intent",
        fake_create_payment_intent,
    )

    operator_id = await create_user("fund-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "fund-contributor@auracles.space",
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
    proposed = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=contributor_headers,
        json=proposal_payload(),
    )
    proposal_id = proposed.json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/accept",
        headers=operator_headers,
    )
    milestone = await client.post(
        f"/v1/projects/{project_id}/milestones",
        headers=contributor_headers,
        json={
            "sequence": 1,
            "name": "Implementation",
            "description": "Build the approved procurement model.",
            "budget": "1500.00",
            "currency": "USD",
        },
    )
    milestone_id = milestone.json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/milestones/finalize",
        headers=contributor_headers,
    )

    funded = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/fund",
        headers=operator_headers,
    )

    async with async_session_factory() as session:
        transaction = await session.scalar(select(Transaction))
        stored_milestone = await session.get(Milestone, UUID(milestone_id))

    body = funded.json()
    assert funded.status_code == 200
    assert body["provider"] == "stripe"
    assert body["client_secret"] == "pi_milestone_secret"
    assert UUID(body["transaction_id"])
    assert transaction is not None
    assert transaction.payer_id == operator_id
    assert transaction.payee_id == contributor_id
    assert transaction.amount == Decimal("1500.00")
    assert transaction.transaction_type == "milestone"
    assert transaction.status == "pending"
    assert transaction.provider == "stripe"
    assert transaction.provider_ref == "pi_milestone_123"
    assert transaction.ref_id == UUID(milestone_id)
    assert transaction.ref_type == "project_milestone"
    assert stored_milestone is not None
    assert stored_milestone.status == "pending"
    payment_intent = calls["payment_intents"][0]
    assert payment_intent["amount"] == Decimal("1500.00")
    assert payment_intent["metadata"]["kind"] == "escrow"
    assert payment_intent["metadata"]["transaction_id"] == str(transaction.id)
    assert payment_intent["metadata"]["project_id"] == project_id
    assert payment_intent["metadata"]["milestone_id"] == milestone_id


async def test_fund_milestone_resumes_existing_pending_payment(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-funding a Milestone with a pending PaymentIntent resumes, not 409s.

    A second Fund click returns the same transaction and client secret instead
    of "already has active funding", and no duplicate transaction is created.
    """

    async def fake_create_customer(
        *, email: str, name: str | None = None, idempotency_key: str | None = None
    ) -> FakeStripeCustomer:
        return FakeStripeCustomer("cus_resume_123")

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: Mapping[str, str],
        idempotency_key: str | None = None,
    ) -> FakeStripePaymentIntent:
        # Same idempotency key -> Stripe returns the same intent; mirror that.
        return FakeStripePaymentIntent("pi_resume_123", "pi_resume_secret")

    monkeypatch.setattr(milestone_service.stripe, "create_customer", fake_create_customer)
    monkeypatch.setattr(
        milestone_service.stripe, "create_payment_intent", fake_create_payment_intent
    )

    operator_id = await create_user("resume-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "resume-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id = await _accept_project_for_milestones(
        client, operator_headers, contributor_headers
    )
    milestone_id = await _finalize_single_milestone_plan(
        client, project_id, contributor_headers
    )

    first = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/fund",
        headers=operator_headers,
    )
    second = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/fund",
        headers=operator_headers,
    )

    async with async_session_factory() as session:
        transaction_count = await session.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.ref_id == UUID(milestone_id),
                Transaction.ref_type == "project_milestone",
            )
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["transaction_id"] == first.json()["transaction_id"]
    assert second.json()["client_secret"] == "pi_resume_secret"
    assert transaction_count == 1


async def create_funded_project_milestone(
    client: AsyncClient,
    *,
    operator_headers: dict[str, str],
    contributor_headers: dict[str, str],
    operator_id: UUID,
    contributor_id: UUID,
) -> tuple[str, str]:
    """Create a Project with one funded Milestone for deliverable tests."""
    created = await client.post(
        "/v1/projects",
        headers=operator_headers,
        json=project_payload(),
    )
    project_id = created.json()["id"]
    proposed = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=contributor_headers,
        json=proposal_payload(),
    )
    proposal_id = proposed.json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/accept",
        headers=operator_headers,
    )
    milestone = await client.post(
        f"/v1/projects/{project_id}/milestones",
        headers=contributor_headers,
        json={
            "sequence": 1,
            "name": "Implementation",
            "description": "Build the approved procurement model.",
            "budget": "1500.00",
            "currency": "USD",
        },
    )
    milestone_id = milestone.json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/milestones/finalize",
        headers=contributor_headers,
    )
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("1500.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("1500.00"),
                transaction_type="milestone",
                status="completed",
                provider="stripe",
                provider_ref="pi_deliverable_123",
                ref_id=UUID(milestone_id),
                ref_type="project_milestone",
            )
            session.add(transaction)
            await session.flush()
            escrow = Escrow(
                ref_id=UUID(milestone_id),
                ref_type="project_milestone",
                amount=Decimal("1500.00"),
                currency="USD",
                status="held",
                release_conditions={
                    "kind": "project_milestone",
                    "milestone_id": milestone_id,
                    "project_id": project_id,
                    "approver_user_id": str(operator_id),
                },
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            stored_project = await session.get(Project, UUID(project_id))
            stored_milestone = await session.get(Milestone, UUID(milestone_id))
            assert stored_project is not None
            assert stored_milestone is not None
            stored_project.status = "in_progress"
            stored_milestone.status = "funded"
            stored_milestone.funded_at = datetime.now(UTC)
            stored_milestone.escrow_id = escrow.id
    return project_id, milestone_id


async def create_disputed_funded_project(
    client: AsyncClient,
    *,
    name: str,
) -> dict[str, Any]:
    """Create a funded Project Milestone with one active Dispute."""
    operator_id = await create_user(f"{name}-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        f"{name}-contributor@auracles.space",
        ["contributor"],
    )
    admin_id, totp_secret = await create_admin_user()
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id, milestone_id = await create_funded_project_milestone(
        client,
        operator_headers=operator_headers,
        contributor_headers=contributor_headers,
        operator_id=operator_id,
        contributor_id=contributor_id,
    )
    raised = await client.post(
        f"/v1/projects/{project_id}/disputes",
        headers=operator_headers,
        json={
            "milestone_id": milestone_id,
            "reason": "Submitted work does not match the agreed scope.",
        },
    )
    return {
        "operator_id": operator_id,
        "contributor_id": contributor_id,
        "admin_id": admin_id,
        "totp_secret": totp_secret,
        "operator_headers": operator_headers,
        "contributor_headers": contributor_headers,
        "admin_headers": auth_headers(admin_id, ["admin"]),
        "project_id": project_id,
        "milestone_id": milestone_id,
        "dispute_id": raised.json()["id"],
        "raised_status": raised.status_code,
    }


async def test_deliverable_revision_approval_and_manual_project_close(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Contributor submits deliverables; Operator approves and closes Project."""
    operator_id = await create_user("deliverable-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "deliverable-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id, milestone_id = await create_funded_project_milestone(
        client,
        operator_headers=operator_headers,
        contributor_headers=contributor_headers,
        operator_id=operator_id,
        contributor_id=contributor_id,
    )

    first_submission = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables",
        headers=contributor_headers,
        json={
            "name": "Draft playbook",
            "description": "Initial implementation playbook.",
            "file_keys": ["workspace/project/draft.pdf"],
        },
    )
    first_deliverable_id = first_submission.json()["id"]
    revision = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables/"
        f"{first_deliverable_id}/request-revision",
        headers=operator_headers,
        json={"revision_notes": "Add rollout risks and KPI ownership."},
    )
    second_submission = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables",
        headers=contributor_headers,
        json={
            "name": "Final playbook",
            "description": "Updated implementation playbook.",
            "file_keys": ["workspace/project/final.pdf"],
        },
    )
    second_deliverable_id = second_submission.json()["id"]
    approved = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables/"
        f"{second_deliverable_id}/approve",
        headers=operator_headers,
    )
    closed = await client.post(
        f"/v1/projects/{project_id}/close",
        headers=operator_headers,
    )

    async with async_session_factory() as session:
        project = await session.get(Project, UUID(project_id))
        milestone = await session.get(Milestone, UUID(milestone_id))
        escrow = await session.scalar(select(Escrow))
        messages = (
            (
                await session.execute(
                    select(WorkspaceMessage)
                    .where(WorkspaceMessage.project_id == UUID(project_id))
                    .order_by(WorkspaceMessage.created_at)
                )
            )
            .scalars()
            .all()
        )

    assert first_submission.status_code == 201
    assert first_submission.json()["status"] == "submitted"
    assert revision.status_code == 200
    assert revision.json()["status"] == "revision_requested"
    assert second_submission.status_code == 201
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert project is not None
    assert project.closed_at is not None
    assert milestone is not None
    assert milestone.status == "approved"
    assert escrow is not None
    assert escrow.status == "released"
    assert [message.system_event for message in messages] == [
        "deliverable_submitted",
        "deliverable_revision_requested",
        "deliverable_submitted",
        "deliverable_approved",
    ]


async def test_approved_deliverable_prefills_framework_draft(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Contributor can turn an approved Project Deliverable into a draft Framework."""
    operator_id = await create_user("publish-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "publish-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id, milestone_id = await create_funded_project_milestone(
        client,
        operator_headers=operator_headers,
        contributor_headers=contributor_headers,
        operator_id=operator_id,
        contributor_id=contributor_id,
    )
    submitted = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables",
        headers=contributor_headers,
        json={
            "name": "Procurement control playbook",
            "description": "Approved procurement control model and rollout guide.",
            "file_keys": ["workspace/project/procurement-playbook.pdf"],
        },
    )
    deliverable_id = submitted.json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables/"
        f"{deliverable_id}/approve",
        headers=operator_headers,
    )

    prefill = await client.get(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables/"
        f"{deliverable_id}/framework-prefill",
        headers=contributor_headers,
    )
    created = await client.post(
        "/v1/frameworks",
        headers=contributor_headers,
        json={
            "title": prefill.json()["title"],
            "description": prefill.json()["description"],
            "category": "framework",
            "sector": "financial_services",
            "industry": "fund_management",
            "function": "operations",
            "tags": prefill.json()["tags"],
            "source_project_id": prefill.json()["source_project_id"],
            "pricing": {
                "price": "499.00",
                "currency": "USD",
                "license_types": ["single_user", "team"],
            },
        },
    )

    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(created.json()["id"]))
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "framework_published_from_project"
            )
        )

    assert prefill.status_code == 200
    assert prefill.json() == {
        "title": "Procurement control playbook",
        "description": "Approved procurement control model and rollout guide.",
        "file_keys": ["workspace/project/procurement-playbook.pdf"],
        "tags": ["project-deliverable"],
        "source_project_id": project_id,
        "source_deliverable_id": deliverable_id,
    }
    assert created.status_code == 201
    assert framework is not None
    assert framework.source_project_id == UUID(project_id)
    assert audit is not None
    assert audit.actor_id == contributor_id
    assert audit.target_id == framework.id


async def test_operator_cannot_build_framework_prefill_from_contributor_deliverable(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Project Operators cannot reuse Contributor deliverables as Framework drafts."""
    operator_id = await create_user(
        "publish-denied-operator@auracles.space",
        ["operator"],
    )
    contributor_id = await create_user(
        "publish-denied-contributor@auracles.space",
        ["contributor"],
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    project_id, milestone_id = await create_funded_project_milestone(
        client,
        operator_headers=operator_headers,
        contributor_headers=contributor_headers,
        operator_id=operator_id,
        contributor_id=contributor_id,
    )
    submitted = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables",
        headers=contributor_headers,
        json={
            "name": "Private delivery pack",
            "description": "A confidential delivery pack owned by the Contributor.",
            "file_keys": ["workspace/project/private-pack.pdf"],
        },
    )
    deliverable_id = submitted.json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables/"
        f"{deliverable_id}/approve",
        headers=operator_headers,
    )

    denied = await client.get(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables/"
        f"{deliverable_id}/framework-prefill",
        headers=operator_headers,
    )

    assert denied.status_code == 403


async def test_workspace_message_upload_session_and_member_visibility(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project members can attach validated upload keys to workspace messages."""
    scan_dispatches: list[str] = []

    class FakePresignedPostTask:
        """Small stand-in for Celery scan dispatch in workspace tests."""

        def delay(self, message_id: str) -> None:
            """Record the message id that would be scanned."""
            scan_dispatches.append(message_id)

    def fake_presigned_post(
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, Any]:
        """Return stable S3 POST data without contacting AWS."""
        return {
            "url": f"https://s3.local/{bucket}",
            "fields": {
                "key": key,
                "Content-Type": mime_type,
                "max_size": str(max_size),
                "expires_in": str(expires_in),
            },
        }

    monkeypatch.setattr(
        workspace_service.s3.storage,
        "presigned_post",
        fake_presigned_post,
    )
    monkeypatch.setattr(
        workspace_service,
        "scan_workspace_upload",
        FakePresignedPostTask(),
    )

    operator_id = await create_user("workspace-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "workspace-contributor@auracles.space",
        ["contributor"],
    )
    outsider_id = await create_user("workspace-outsider@auracles.space", ["operator"])
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    outsider_headers = auth_headers(outsider_id, ["operator"])

    created = await client.post(
        "/v1/projects",
        headers=operator_headers,
        json=project_payload(),
    )
    project_id = created.json()["id"]
    proposed = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=contributor_headers,
        json=proposal_payload(),
    )
    proposal_id = proposed.json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/accept",
        headers=operator_headers,
    )

    upload = await client.post(
        f"/v1/projects/{project_id}/messages/uploads",
        headers=contributor_headers,
        json={
            "file_name": "draft.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1200,
        },
    )
    file_key = upload.json()["s3_key"]
    message = await client.post(
        f"/v1/projects/{project_id}/messages",
        headers=contributor_headers,
        json={
            "body": "Draft attached for review.",
            "file_keys": [file_key],
        },
    )
    contributor_messages = await client.get(
        f"/v1/projects/{project_id}/messages",
        headers=contributor_headers,
    )
    operator_messages = await client.get(
        f"/v1/projects/{project_id}/messages",
        headers=operator_headers,
    )
    outsider_messages = await client.get(
        f"/v1/projects/{project_id}/messages",
        headers=outsider_headers,
    )

    async with async_session_factory() as session:
        upload_session = await session.scalar(select(WorkspaceUploadSession))
        stored_message = await session.get(
            WorkspaceMessage,
            UUID(message.json()["id"]),
        )

    assert upload.status_code == 201
    assert upload.json()["url"] == "https://s3.local/auracles-artifacts-dev"
    assert file_key.startswith(f"workspace/{project_id}/{contributor_id}/")
    assert message.status_code == 201
    assert message.json()["scan_status"] == "pending_scan"
    assert contributor_messages.status_code == 200
    assert [item["id"] for item in contributor_messages.json()["messages"]] == [
        message.json()["id"]
    ]
    assert operator_messages.status_code == 200
    assert operator_messages.json()["messages"] == []
    assert outsider_messages.status_code == 403
    assert upload_session is not None
    assert upload_session.consumed_at is not None
    assert stored_message is not None
    assert stored_message.file_keys == [file_key]
    assert scan_dispatches == [message.json()["id"]]


async def test_project_member_raises_dispute_and_admin_resolves_split(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project member disputes a Milestone; Admin resolves by split."""
    del migrated_database, project_context
    refund_calls: list[dict[str, Any]] = []
    notification_calls: list[dict[str, Any]] = []
    fake_redis = FakeRedis()

    async def override_redis() -> FakeRedis:
        """Return Redis test double for admin TOTP verification."""
        return fake_redis

    async def fake_create_refund(
        *,
        payment_intent_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> FakeStripeRefund:
        """Record the Stripe refund portion of a split resolution."""
        refund_calls.append(
            {
                "payment_intent_id": payment_intent_id,
                "amount": amount,
                "currency": currency,
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripeRefund("re_project_split_123")

    app.dependency_overrides[get_redis] = override_redis
    monkeypatch.setattr(escrow_service.stripe, "create_refund", fake_create_refund)
    monkeypatch.setattr(
        dispute_service,
        "dispatch_project_notification",
        FakeNotificationTask(notification_calls),
    )

    operator_id = await create_user("dispute-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "dispute-contributor@auracles.space",
        ["contributor"],
    )
    admin_id, totp_secret = await create_admin_user()
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])
    admin_headers = auth_headers(admin_id, ["admin"])
    project_id, milestone_id = await create_funded_project_milestone(
        client,
        operator_headers=operator_headers,
        contributor_headers=contributor_headers,
        operator_id=operator_id,
        contributor_id=contributor_id,
    )

    raised = await client.post(
        f"/v1/projects/{project_id}/disputes",
        headers=operator_headers,
        json={
            "milestone_id": milestone_id,
            "reason": "Submitted work does not match the agreed scope.",
        },
    )
    listed = await client.get(
        f"/v1/projects/{project_id}/disputes",
        headers=contributor_headers,
    )
    dispute_id = raised.json()["id"]
    bad_split = await client.post(
        f"/v1/admin/projects/disputes/{dispute_id}/resolve",
        headers=admin_headers,
        json={
            "resolution_type": "split",
            "release_amount": "900.00",
            "refund_amount": "500.00",
            "resolution_notes": "Amounts do not match the funded milestone.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )
    resolved = await client.post(
        f"/v1/admin/projects/disputes/{dispute_id}/resolve",
        headers=admin_headers,
        json={
            "resolution_type": "split",
            "release_amount": "900.00",
            "refund_amount": "600.00",
            "resolution_notes": "Partial delivery accepted by support.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )
    double_resolve = await client.post(
        f"/v1/admin/projects/disputes/{dispute_id}/resolve",
        headers=admin_headers,
        json={
            "resolution_type": "split",
            "release_amount": "900.00",
            "refund_amount": "600.00",
            "resolution_notes": "Duplicate resolution should be blocked.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )

    async with async_session_factory() as session:
        project = await session.get(Project, UUID(project_id))
        milestone = await session.get(Milestone, UUID(milestone_id))
        dispute = await session.get(Dispute, UUID(dispute_id))
        escrow = await session.get(Escrow, milestone.escrow_id) if milestone else None
        transactions = (
            (
                await session.execute(
                    select(Transaction).order_by(Transaction.created_at)
                )
            )
            .scalars()
            .all()
        )
        messages = (
            (
                await session.execute(
                    select(WorkspaceMessage)
                    .where(WorkspaceMessage.project_id == UUID(project_id))
                    .order_by(WorkspaceMessage.created_at)
                )
            )
            .scalars()
            .all()
        )

    app.dependency_overrides.pop(get_redis, None)

    assert raised.status_code == 201
    assert raised.json()["status"] == "open"
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["disputes"]] == [dispute_id]
    assert bad_split.status_code == 422
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution_type"] == "split"
    assert double_resolve.status_code == 409
    assert project is not None
    assert project.status == "delivered"
    assert milestone is not None
    assert milestone.status == "approved"
    assert dispute is not None
    assert dispute.status == "resolved"
    assert dispute.release_amount == Decimal("900.00")
    assert dispute.refund_amount == Decimal("600.00")
    assert escrow is not None
    assert escrow.status == "released"
    assert escrow.released_by == admin_id
    assert sorted(
        (transaction.transaction_type, transaction.amount, transaction.status)
        for transaction in transactions
    ) == sorted(
        [
            ("milestone", Decimal("1500.00"), "refunded"),
            ("milestone", Decimal("900.00"), "completed"),
            ("refund", Decimal("600.00"), "refunded"),
        ]
    )
    assert refund_calls == [
        {
            "payment_intent_id": "pi_deliverable_123",
            "amount": Decimal("600.00"),
            "currency": "USD",
            "idempotency_key": f"escrow_split_refund:{escrow.id}",
        }
    ]
    assert [call["notification_type"] for call in notification_calls] == [
        "dispute_raised",
        "dispute_resolved_split",
        "dispute_resolved_split",
    ]
    assert [message.system_event for message in messages] == [
        "dispute_raised",
        "dispute_resolved",
    ]


async def test_admin_resolves_dispute_release_to_contributor(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release resolution awards the full Milestone escrow to Contributor."""
    del migrated_database, project_context
    notification_calls: list[dict[str, Any]] = []
    fake_redis = FakeRedis()

    async def override_redis() -> FakeRedis:
        """Return Redis test double for admin TOTP verification."""
        return fake_redis

    async def unexpected_refund(**kwargs: Any) -> FakeStripeRefund:
        """Fail if release resolution tries to call Stripe refund."""
        raise AssertionError(f"Unexpected refund call: {kwargs}")

    app.dependency_overrides[get_redis] = override_redis
    monkeypatch.setattr(escrow_service.stripe, "create_refund", unexpected_refund)
    monkeypatch.setattr(dispute_service.stripe, "create_refund", unexpected_refund)
    monkeypatch.setattr(
        dispute_service,
        "dispatch_project_notification",
        FakeNotificationTask(notification_calls),
    )
    context = await create_disputed_funded_project(client, name="release-dispute")

    resolved = await client.post(
        f"/v1/admin/projects/disputes/{context['dispute_id']}/resolve",
        headers=context["admin_headers"],
        json={
            "resolution_type": "release",
            "resolution_notes": "Contributor delivered enough to release escrow.",
            "totp_code": pyotp.TOTP(context["totp_secret"]).now(),
        },
    )

    async with async_session_factory() as session:
        project = await session.get(Project, UUID(context["project_id"]))
        milestone = await session.get(Milestone, UUID(context["milestone_id"]))
        dispute = await session.get(Dispute, UUID(context["dispute_id"]))
        escrow = await session.get(Escrow, milestone.escrow_id) if milestone else None

    app.dependency_overrides.pop(get_redis, None)

    assert context["raised_status"] == 201
    assert resolved.status_code == 200
    assert resolved.json()["resolution_type"] == "release"
    assert project is not None
    assert project.status == "delivered"
    assert milestone is not None
    assert milestone.status == "approved"
    assert dispute is not None
    assert dispute.status == "resolved"
    assert dispute.release_amount is None
    assert dispute.refund_amount is None
    assert escrow is not None
    assert escrow.status == "released"
    assert escrow.released_by == context["admin_id"]
    assert [call["notification_type"] for call in notification_calls] == [
        "dispute_raised",
        "dispute_resolved_release",
        "dispute_resolved_release",
    ]


async def test_admin_resolves_dispute_refund_to_operator(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refund resolution returns the full Milestone escrow to Operator."""
    del migrated_database, project_context
    refund_calls: list[dict[str, Any]] = []
    notification_calls: list[dict[str, Any]] = []
    fake_redis = FakeRedis()

    async def override_redis() -> FakeRedis:
        """Return Redis test double for admin TOTP verification."""
        return fake_redis

    async def fake_create_refund(
        *,
        payment_intent_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> FakeStripeRefund:
        """Record the Stripe full refund request."""
        refund_calls.append(
            {
                "payment_intent_id": payment_intent_id,
                "amount": amount,
                "currency": currency,
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripeRefund("re_project_refund_123")

    app.dependency_overrides[get_redis] = override_redis
    monkeypatch.setattr(dispute_service.stripe, "create_refund", fake_create_refund)
    monkeypatch.setattr(
        dispute_service,
        "dispatch_project_notification",
        FakeNotificationTask(notification_calls),
    )
    context = await create_disputed_funded_project(client, name="refund-dispute")

    resolved = await client.post(
        f"/v1/admin/projects/disputes/{context['dispute_id']}/resolve",
        headers=context["admin_headers"],
        json={
            "resolution_type": "refund",
            "resolution_notes": "Operator refund approved after admin review.",
            "totp_code": pyotp.TOTP(context["totp_secret"]).now(),
        },
    )

    async with async_session_factory() as session:
        project = await session.get(Project, UUID(context["project_id"]))
        milestone = await session.get(Milestone, UUID(context["milestone_id"]))
        dispute = await session.get(Dispute, UUID(context["dispute_id"]))
        escrow = await session.get(Escrow, milestone.escrow_id) if milestone else None
        transaction = (
            await session.get(Transaction, escrow.transaction_id) if escrow else None
        )

    app.dependency_overrides.pop(get_redis, None)

    assert context["raised_status"] == 201
    assert resolved.status_code == 200
    assert resolved.json()["resolution_type"] == "refund"
    assert project is not None
    assert project.status == "delivered"
    assert milestone is not None
    assert milestone.status == "cancelled"
    assert dispute is not None
    assert dispute.status == "resolved"
    assert dispute.release_amount is None
    assert dispute.refund_amount is None
    assert escrow is not None
    assert escrow.status == "refunded"
    assert transaction is not None
    assert transaction.status == "refunded"
    assert refund_calls == [
        {
            "payment_intent_id": "pi_deliverable_123",
            "amount": Decimal("1500.00"),
            "currency": "USD",
            "idempotency_key": f"escrow_dispute_refund:{escrow.id}",
        }
    ]
    assert [call["notification_type"] for call in notification_calls] == [
        "dispute_raised",
        "dispute_resolved_refund",
        "dispute_resolved_refund",
    ]


async def _assigned_finalized_project_with_amendment(
    client: AsyncClient,
    operator_headers: dict[str, str],
    contributor_headers: dict[str, str],
) -> tuple[str, str, str]:
    """Drive a Project to assigned+finalized and propose a budget amendment.

    Returns the project, proposal, and amendment ids. The amendment is proposed
    by the Contributor, leaving the Operator as the accepting counterparty.
    """
    created = await client.post(
        "/v1/projects", headers=operator_headers, json=project_payload()
    )
    project_id = created.json()["id"]
    proposed = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=contributor_headers,
        json=proposal_payload(),
    )
    proposal_id = proposed.json()["id"]
    await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/accept",
        headers=operator_headers,
    )
    async with async_session_factory() as session:
        project = await session.scalar(select(Project).where(Project.id == project_id))
        assert project is not None
        project.milestone_plan_status = "finalized"
        await session.commit()

    amendment = await client.post(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/amendments",
        headers=contributor_headers,
        json={
            "change_type": "budget",
            "after": {"budget": "1750.00"},
            "reason": "Scope needs deeper implementation support.",
        },
    )
    return project_id, proposal_id, amendment.json()["id"]


async def test_operator_edits_open_project_and_validates_budget_and_status(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Open Projects accept field edits; bad budgets and assigned state are blocked."""
    operator_id = await create_user("edit-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "edit-contributor@auracles.space", ["contributor"]
    )
    operator_headers = auth_headers(operator_id, ["operator"])

    created = await client.post(
        "/v1/projects", headers=operator_headers, json=project_payload()
    )
    project_id = created.json()["id"]

    edited = await client.patch(
        f"/v1/projects/{project_id}",
        headers=operator_headers,
        json={"title": "Procurement Playbook v2", "budget_max": "2500.00"},
    )
    bad_budget = await client.patch(
        f"/v1/projects/{project_id}",
        headers=operator_headers,
        json={"budget_min": "3000.00"},
    )

    # Assign the Project, after which it can no longer be edited.
    proposed = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=auth_headers(contributor_id, ["contributor"]),
        json=proposal_payload(),
    )
    await client.post(
        f"/v1/projects/{project_id}/proposals/{proposed.json()['id']}/accept",
        headers=operator_headers,
    )
    edit_after_assign = await client.patch(
        f"/v1/projects/{project_id}",
        headers=operator_headers,
        json={"title": "Too late"},
    )

    assert edited.status_code == 200
    assert edited.json()["title"] == "Procurement Playbook v2"
    assert edited.json()["budget_max"] == "2500.00"
    assert bad_budget.status_code == 422
    assert edit_after_assign.status_code == 409


async def test_operator_lists_all_proposals_and_contributor_lists_own(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Operators see every Proposal; Contributors see only their own."""
    operator_id = await create_user("list-operator@auracles.space", ["operator"])
    first_id = await create_user("list-first@auracles.space", ["contributor"])
    second_id = await create_user("list-second@auracles.space", ["contributor"])
    operator_headers = auth_headers(operator_id, ["operator"])

    created = await client.post(
        "/v1/projects", headers=operator_headers, json=project_payload()
    )
    project_id = created.json()["id"]
    for contributor in (first_id, second_id):
        await client.post(
            f"/v1/projects/{project_id}/proposals",
            headers=auth_headers(contributor, ["contributor"]),
            json=proposal_payload(),
        )

    all_proposals = await client.get(
        f"/v1/projects/{project_id}/proposals", headers=operator_headers
    )
    mine = await client.get(
        f"/v1/projects/{project_id}/proposals/mine",
        headers=auth_headers(first_id, ["contributor"]),
    )

    assert all_proposals.status_code == 200
    assert len(all_proposals.json()["proposals"]) == 2
    assert mine.status_code == 200
    mine_ids = {item["contributor_id"] for item in mine.json()["proposals"]}
    assert mine_ids == {str(first_id)}


async def test_contributor_withdraws_pending_proposal_only_once(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """A pending Proposal can be withdrawn once; a second attempt conflicts."""
    operator_id = await create_user("wd-operator@auracles.space", ["operator"])
    contributor_id = await create_user("wd-contributor@auracles.space", ["contributor"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])

    created = await client.post(
        "/v1/projects",
        headers=auth_headers(operator_id, ["operator"]),
        json=project_payload(),
    )
    project_id = created.json()["id"]
    proposed = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=contributor_headers,
        json=proposal_payload(),
    )
    proposal_id = proposed.json()["id"]

    withdrawn = await client.patch(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/withdraw",
        headers=contributor_headers,
    )
    withdrawn_again = await client.patch(
        f"/v1/projects/{project_id}/proposals/{proposal_id}/withdraw",
        headers=contributor_headers,
    )

    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"
    assert withdrawn_again.status_code == 409


async def test_counterparty_rejects_amendment_and_proposer_cannot(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Only the counterparty may reject a pending amendment."""
    operator_id = await create_user("rej-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "rej-contributor@auracles.space", ["contributor"]
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])

    (
        project_id,
        proposal_id,
        amendment_id,
    ) = await _assigned_finalized_project_with_amendment(
        client, operator_headers, contributor_headers
    )
    base = (
        f"/v1/projects/{project_id}/proposals/{proposal_id}/amendments/{amendment_id}"
    )

    proposer_reject = await client.post(f"{base}/reject", headers=contributor_headers)
    counterparty_reject = await client.post(f"{base}/reject", headers=operator_headers)

    assert proposer_reject.status_code == 403
    assert counterparty_reject.status_code == 200
    assert counterparty_reject.json()["status"] == "rejected"


async def test_proposer_withdraws_amendment_and_counterparty_cannot(
    client: AsyncClient,
    migrated_database: None,
    project_context: dict[str, Any],
) -> None:
    """Only the proposer may withdraw their own pending amendment."""
    operator_id = await create_user("amw-operator@auracles.space", ["operator"])
    contributor_id = await create_user(
        "amw-contributor@auracles.space", ["contributor"]
    )
    operator_headers = auth_headers(operator_id, ["operator"])
    contributor_headers = auth_headers(contributor_id, ["contributor"])

    (
        project_id,
        proposal_id,
        amendment_id,
    ) = await _assigned_finalized_project_with_amendment(
        client, operator_headers, contributor_headers
    )
    base = (
        f"/v1/projects/{project_id}/proposals/{proposal_id}/amendments/{amendment_id}"
    )

    counterparty_withdraw = await client.patch(
        f"{base}/withdraw", headers=operator_headers
    )
    proposer_withdraw = await client.patch(
        f"{base}/withdraw", headers=contributor_headers
    )

    assert counterparty_withdraw.status_code == 403
    assert proposer_withdraw.status_code == 200
    assert proposer_withdraw.json()["status"] == "withdrawn"
