"""Integration tests for Phase 4a Project CRUD and proposal flow."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
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
from app.modules.financials.models import Escrow, Transaction
from app.modules.projects import milestone_service
from app.modules.projects.models import Milestone, Project, Proposal, ProposalAmendment
from app.modules.workspace.models import WorkspaceMessage
from app.shared.models.audit_log import AuditLog


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
            await session.execute(delete(Milestone))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(ProposalAmendment))
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
