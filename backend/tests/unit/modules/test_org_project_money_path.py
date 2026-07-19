"""Unit tests for the organization Project money-path services (Task 7).

Exercises the service layer directly for org-operated Project funding, approval,
auto-approval, and dispute-refund routing: funding stamps ``payer_org_id`` and
charges the org Stripe customer; approval releases Escrow to the Contributor
beneficiary (individual and org Contributor); auto-approval fires for an org
Project and notifies org admins; dispute refund settles against the org-payer
transaction; and a suspended operator capability blocks funding.

Maps to: Task 7 in docs/superpowers/specs/2026-07-10-org-operator-design.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, Transaction
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.modules.projects import dispute_service, milestone_service
from app.modules.projects import notifications as project_notifications
from app.modules.projects.models import (
    Deliverable,
    Dispute,
    Milestone,
    Project,
    Proposal,
)
from app.modules.projects.schemas import (
    DeliverableRevisionRequest,
    DisputeCreateRequest,
)
from app.modules.workspace.models import WorkspaceMessage
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import projects_beat
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio

BACKEND_DIR = Path(__file__).resolve().parents[3]


class FakeStripePaymentIntent:
    """Small stand-in for a Stripe PaymentIntent result."""

    def __init__(self, payment_intent_id: str, client_secret: str) -> None:
        """Store the provider intent id and browser client secret."""
        self.id = payment_intent_id
        self.client_secret = client_secret


class FakeStripeRefund:
    """Small stand-in for a Stripe refund result."""

    def __init__(self, refund_id: str) -> None:
        """Store the provider refund id and status."""
        self.id = refund_id
        self.status = "succeeded"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for money-path unit tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url, pool_pre_ping=True
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def money_path_state() -> AsyncIterator[None]:
    """Reset Project and financial rows around each money-path unit test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete Project and financial rows in dependency order."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(WorkspaceMessage))
            await session.execute(delete(Dispute))
            await session.execute(delete(Deliverable))
            await session.execute(delete(Milestone))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
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


async def _create_user(prefix: str, roles: list[str] | None = None) -> UUID:
    """Create one verified user with optional approved roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            for role in roles or []:
                session.add(
                    UserRole(
                        user_id=user.id, role=role, approved_at=datetime.now(UTC)
                    )
                )
            return user.id


async def _seed_org(
    *,
    prefix: str,
    operator_status: str = "active",
    stripe_customer_id: str | None = "cus_org_unit",
) -> dict[str, Any]:
    """Create an org with an owner, an admin, a member, and the operator cap."""
    owner_id = await _create_user(f"{prefix}-owner")
    admin_id = await _create_user(f"{prefix}-admin")
    member_id = await _create_user(f"{prefix}-member")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"{prefix}-{uuid4().hex[:6]}",
                name=prefix,
                country="GB",
                created_by=owner_id,
                stripe_customer_id=stripe_customer_id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner_id, role="owner"))
            session.add(OrgMember(org_id=org.id, user_id=admin_id, role="admin"))
            session.add(OrgMember(org_id=org.id, user_id=member_id, role="member"))
            session.add(
                OrgCapability(
                    org_id=org.id, capability="operator", status=operator_status
                )
            )
            org_id = org.id
    return {
        "org_id": org_id,
        "owner_id": owner_id,
        "admin_id": admin_id,
        "member_id": member_id,
    }


async def _seed_org_project(
    *,
    org_id: UUID,
    contributor_id: UUID | None,
    contributor_org_id: UUID | None = None,
    delivering_member_id: UUID | None = None,
    milestone_plan_status: str = "finalized",
    milestone_status: str = "pending",
    project_status: str = "assigned",
    with_escrow: bool = False,
) -> dict[str, Any]:
    """Seed an org-operated Project with an accepted Proposal and one Milestone."""
    async with async_session_factory() as session:
        async with session.begin():
            project = Project(
                operator_id=None,
                operator_org_id=org_id,
                title="Org Project",
                description="Org-operated project.",
                category="operations",
                required_deliverables=[],
                budget_min=Decimal("1000.00"),
                budget_max=Decimal("2000.00"),
                currency="USD",
                deadline=datetime(2026, 8, 1).date(),
                expires_at=datetime.now(UTC) + timedelta(days=30),
                status=project_status,
                milestone_plan_status=milestone_plan_status,
            )
            session.add(project)
            await session.flush()
            proposal = Proposal(
                project_id=project.id,
                contributor_id=contributor_id,
                contributor_org_id=contributor_org_id,
                delivering_member_id=delivering_member_id,
                scope="Deliver the work.",
                budget=Decimal("1500.00"),
                currency="USD",
                timeline_days=21,
                deliverables=[],
                status="accepted",
                accepted_at=datetime.now(UTC),
            )
            session.add(proposal)
            await session.flush()
            project.accepted_proposal_id = proposal.id
            milestone = Milestone(
                project_id=project.id,
                sequence=1,
                name="Implementation",
                description="Build the model.",
                budget=Decimal("1500.00"),
                currency="USD",
                status=milestone_status,
            )
            session.add(milestone)
            await session.flush()

            escrow_id: UUID | None = None
            if with_escrow:
                transaction = Transaction(
                    payer_id=None,
                    payer_org_id=org_id,
                    payee_id=contributor_id,
                    payee_org_id=contributor_org_id,
                    amount=Decimal("1500.00"),
                    currency="USD",
                    platform_commission=Decimal("0.00"),
                    net_amount=Decimal("1500.00"),
                    transaction_type="milestone",
                    status="completed",
                    provider="stripe",
                    provider_ref="pi_org_unit",
                    ref_id=milestone.id,
                    ref_type="project_milestone",
                )
                session.add(transaction)
                await session.flush()
                escrow = Escrow(
                    ref_id=milestone.id,
                    ref_type="project_milestone",
                    amount=Decimal("1500.00"),
                    currency="USD",
                    status="held",
                    release_conditions={
                        "kind": "project_milestone",
                        "milestone_id": str(milestone.id),
                        "project_id": str(project.id),
                        "approver_org_id": str(org_id),
                    },
                    transaction_id=transaction.id,
                )
                session.add(escrow)
                await session.flush()
                milestone.escrow_id = escrow.id
                milestone.funded_at = datetime.now(UTC)
                escrow_id = escrow.id
            return {
                "project_id": project.id,
                "proposal_id": proposal.id,
                "milestone_id": milestone.id,
                "escrow_id": escrow_id,
            }


async def _seed_submitted_deliverable(
    *,
    milestone_id: UUID,
    contributor_id: UUID | None,
    contributor_org_id: UUID | None = None,
    submitted_at: datetime | None = None,
) -> UUID:
    """Seed one scan-clean, submitted Deliverable against a Milestone."""
    async with async_session_factory() as session:
        async with session.begin():
            deliverable = Deliverable(
                milestone_id=milestone_id,
                contributor_id=contributor_id,
                contributor_org_id=contributor_org_id,
                name="Final",
                description="Work.",
                file_keys=["workspace/project/final.pdf"],
                status="submitted",
                scan_status="visible",
                submitted_at=submitted_at or datetime.now(UTC),
            )
            session.add(deliverable)
            await session.flush()
            # Move the Milestone into the review state approval expects.
            milestone = await session.get(Milestone, milestone_id)
            assert milestone is not None
            milestone.status = "submitted"
            milestone.submitted_at = datetime.now(UTC)
            return deliverable.id


def _patch_notifications(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record queued Project notification dispatches without Celery/Redis."""
    calls: list[dict[str, Any]] = []

    class _FakeTask:
        def delay(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(
        project_notifications, "dispatch_project_notification", _FakeTask()
    )
    return calls


async def test_org_funding_stamps_payer_org_and_charges_org_customer(
    migrated_database: None,
    money_path_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Org Milestone funding stamps payer_org_id and charges the org customer."""
    del migrated_database, money_path_state
    org = await _seed_org(prefix="fundunit", stripe_customer_id="cus_org_fund")
    contributor_id = await _create_user("fundunit-contrib", ["contributor"])
    seed = await _seed_org_project(org_id=org["org_id"], contributor_id=contributor_id)

    captured: dict[str, Any] = {}

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: Mapping[str, str],
        idempotency_key: str | None = None,
    ) -> FakeStripePaymentIntent:
        captured["customer_id"] = customer_id
        captured["metadata"] = dict(metadata)
        return FakeStripePaymentIntent("pi_fund_unit", "secret_fund_unit")

    monkeypatch.setattr(
        milestone_service.stripe, "create_payment_intent", fake_create_payment_intent
    )

    async with async_session_factory() as db:
        result = await milestone_service.fund_org_milestone(
            db=db,
            org_id=org["org_id"],
            actor_id=org["admin_id"],
            project_id=seed["project_id"],
            milestone_id=seed["milestone_id"],
        )

    assert result.client_secret == "secret_fund_unit"
    assert captured["customer_id"] == "cus_org_fund"
    assert captured["metadata"]["payer_org_id"] == str(org["org_id"])
    # The release conditions carry the org, not a single approver user.
    assert str(org["org_id"]) in captured["metadata"]["release_conditions"]
    assert "approver_org_id" in captured["metadata"]["release_conditions"]

    async with async_session_factory() as session:
        transaction = await session.scalar(
            select(Transaction).where(
                Transaction.ref_id == seed["milestone_id"],
                Transaction.ref_type == "project_milestone",
            )
        )
    assert transaction is not None
    assert transaction.payer_id is None
    assert transaction.payer_org_id == org["org_id"]


async def test_org_funding_blocked_when_capability_suspended(
    migrated_database: None,
    money_path_state: None,
) -> None:
    """Funding an org Milestone with a suspended operator capability is 403."""
    del migrated_database, money_path_state
    org = await _seed_org(prefix="suspend", operator_status="suspended")
    contributor_id = await _create_user("suspend-contrib", ["contributor"])
    seed = await _seed_org_project(org_id=org["org_id"], contributor_id=contributor_id)

    async with async_session_factory() as db:
        with pytest.raises(Exception) as exc_info:
            await milestone_service.fund_org_milestone(
                db=db,
                org_id=org["org_id"],
                actor_id=org["admin_id"],
                project_id=seed["project_id"],
                milestone_id=seed["milestone_id"],
            )
    assert getattr(exc_info.value, "status_code", None) == 403


async def test_org_dispute_allowed_when_capability_suspended(
    migrated_database: None,
    money_path_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A suspended org can still dispute an in-flight funded milestone.

    Suspension blocks new money-out actions, but disputing protects escrow
    already committed; withholding it would let the funded milestone
    auto-release with no recourse.
    """
    del migrated_database, money_path_state
    _patch_notifications(monkeypatch)
    org = await _seed_org(prefix="suspend-dispute", operator_status="suspended")
    contributor_id = await _create_user("suspend-dispute-contrib", ["contributor"])
    seed = await _seed_org_project(
        org_id=org["org_id"],
        contributor_id=contributor_id,
        milestone_status="funded",
        project_status="in_progress",
        with_escrow=True,
    )

    async with async_session_factory() as db:
        dispute = await dispute_service.create_org_dispute(
            db=db,
            org_id=org["org_id"],
            actor_id=org["admin_id"],
            project_id=seed["project_id"],
            payload=DisputeCreateRequest(
                milestone_id=seed["milestone_id"],
                reason="Submitted work does not match the agreed scope here.",
            ),
        )
    # The raiser side is recorded without exposing the acting member's id.
    assert dispute.raised_by_side == "operator"

    async with async_session_factory() as session:
        message = await session.scalar(
            select(WorkspaceMessage).where(
                WorkspaceMessage.system_event == "dispute_raised"
            )
        )
    assert message is not None
    assert message.system_payload == {
        "dispute_id": str(dispute.id),
        "milestone_id": str(seed["milestone_id"]),
        "raised_by_side": "operator",
    }


def test_dispute_response_hides_raiser_identity() -> None:
    """The member-facing dispute schema exposes the side, not the raiser id."""
    from app.modules.projects.schemas import DisputeResponse

    assert "raised_by" not in DisputeResponse.model_fields
    assert "raised_by_side" in DisputeResponse.model_fields


async def test_org_funding_requires_org_stripe_customer(
    migrated_database: None,
    money_path_state: None,
) -> None:
    """Funding without an org Stripe customer returns 402 (no lazy create)."""
    del migrated_database, money_path_state
    org = await _seed_org(prefix="nocustomer", stripe_customer_id=None)
    contributor_id = await _create_user("nocustomer-contrib", ["contributor"])
    seed = await _seed_org_project(org_id=org["org_id"], contributor_id=contributor_id)

    async with async_session_factory() as db:
        with pytest.raises(Exception) as exc_info:
            await milestone_service.fund_org_milestone(
                db=db,
                org_id=org["org_id"],
                actor_id=org["admin_id"],
                project_id=seed["project_id"],
                milestone_id=seed["milestone_id"],
            )
    assert getattr(exc_info.value, "status_code", None) == 402


async def test_org_approval_releases_escrow_to_individual_contributor(
    migrated_database: None,
    money_path_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approving an org Deliverable releases Escrow to the individual Contributor."""
    del migrated_database, money_path_state
    _patch_notifications(monkeypatch)
    org = await _seed_org(prefix="approveind")
    contributor_id = await _create_user("approveind-contrib", ["contributor"])
    seed = await _seed_org_project(
        org_id=org["org_id"],
        contributor_id=contributor_id,
        milestone_status="funded",
        project_status="in_progress",
        with_escrow=True,
    )
    deliverable_id = await _seed_submitted_deliverable(
        milestone_id=seed["milestone_id"], contributor_id=contributor_id
    )

    async with async_session_factory() as db:
        await milestone_service.approve_org_deliverable(
            db=db,
            org_id=org["org_id"],
            actor_id=org["admin_id"],
            project_id=seed["project_id"],
            deliverable_id=deliverable_id,
        )

    async with async_session_factory() as session:
        escrow = await session.get(Escrow, seed["escrow_id"])
        transaction = await session.scalar(
            select(Transaction).where(Transaction.ref_id == seed["milestone_id"])
        )
    assert escrow is not None and escrow.status == "released"
    assert transaction is not None
    assert transaction.payee_id == contributor_id
    # The org remains the payer through release.
    assert transaction.payer_org_id == org["org_id"]


async def test_org_operator_can_request_deliverable_revision(
    migrated_database: None,
    money_path_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An org operator can return submitted work without releasing Escrow."""
    del migrated_database, money_path_state
    _patch_notifications(monkeypatch)
    org = await _seed_org(prefix="revision")
    contributor_id = await _create_user("revision-contrib", ["contributor"])
    seed = await _seed_org_project(
        org_id=org["org_id"],
        contributor_id=contributor_id,
        milestone_status="funded",
        project_status="in_progress",
    )
    deliverable_id = await _seed_submitted_deliverable(
        milestone_id=seed["milestone_id"],
        contributor_id=contributor_id,
    )

    async with async_session_factory() as db:
        revised = await milestone_service.request_org_deliverable_revision(
            db=db,
            org_id=org["org_id"],
            actor_id=org["admin_id"],
            project_id=seed["project_id"],
            milestone_id=seed["milestone_id"],
            deliverable_id=deliverable_id,
            payload=DeliverableRevisionRequest(
                revision_notes="Please align the controls with the agreed scope."
            ),
        )

    assert revised.status == "revision_requested"
    assert revised.revision_notes == "Please align the controls with the agreed scope."


async def test_org_approval_releases_escrow_to_org_contributor(
    migrated_database: None,
    money_path_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approving credits an org Contributor beneficiary via payee_org_id."""
    del migrated_database, money_path_state
    _patch_notifications(monkeypatch)
    operator_org = await _seed_org(prefix="approveop")
    contributor_org = await _seed_org(prefix="approvecontrib")
    delivering_user_id = await _create_user("approve-delivery")
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(
                org_id=contributor_org["org_id"],
                user_id=delivering_user_id,
                role="member",
            )
            session.add(member)
            await session.flush()
            delivering_member_id = member.id

    seed = await _seed_org_project(
        org_id=operator_org["org_id"],
        contributor_id=None,
        contributor_org_id=contributor_org["org_id"],
        delivering_member_id=delivering_member_id,
        milestone_status="funded",
        project_status="in_progress",
        with_escrow=True,
    )
    deliverable_id = await _seed_submitted_deliverable(
        milestone_id=seed["milestone_id"],
        contributor_id=None,
        contributor_org_id=contributor_org["org_id"],
    )

    async with async_session_factory() as db:
        await milestone_service.approve_org_deliverable(
            db=db,
            org_id=operator_org["org_id"],
            actor_id=operator_org["admin_id"],
            project_id=seed["project_id"],
            deliverable_id=deliverable_id,
        )

    async with async_session_factory() as session:
        escrow = await session.get(Escrow, seed["escrow_id"])
        transaction = await session.scalar(
            select(Transaction).where(Transaction.ref_id == seed["milestone_id"])
        )
    assert escrow is not None and escrow.status == "released"
    assert transaction is not None
    # Beneficiary resolution routes an org Contributor to payee_org_id.
    assert transaction.payee_id is None
    assert transaction.payee_org_id == contributor_org["org_id"]
    assert transaction.payer_org_id == operator_org["org_id"]


async def test_auto_approval_fires_for_org_project_and_notifies_org_admins(
    migrated_database: None,
    money_path_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto-approval releases an org Milestone's Escrow and notifies org admins."""
    del migrated_database, money_path_state
    notifications = _patch_notifications(monkeypatch)
    org = await _seed_org(prefix="autoorg")
    contributor_id = await _create_user("autoorg-contrib", ["contributor"])
    seed = await _seed_org_project(
        org_id=org["org_id"],
        contributor_id=contributor_id,
        milestone_status="funded",
        project_status="in_progress",
        with_escrow=True,
    )
    # Submit the Deliverable fifteen days ago so it is past the fourteen-day idle
    # window the auto-approval sweep enforces.
    await _seed_submitted_deliverable(
        milestone_id=seed["milestone_id"],
        contributor_id=contributor_id,
        submitted_at=datetime.now(UTC) - timedelta(days=15),
    )

    auto_approved = await projects_beat._auto_approve_deliverables()

    assert auto_approved == 1
    async with async_session_factory() as session:
        escrow = await session.get(Escrow, seed["escrow_id"])
        milestone = await session.get(Milestone, seed["milestone_id"])
    assert escrow is not None and escrow.status == "released"
    assert milestone is not None and milestone.status == "auto_approved"

    operator_recipients = {
        call["user_id"]
        for call in notifications
        if call["notification_type"] == "deliverable_auto_approved"
        and call["user_id"] in {str(org["owner_id"]), str(org["admin_id"])}
    }
    assert operator_recipients == {str(org["owner_id"]), str(org["admin_id"])}


async def test_org_dispute_refund_routes_to_payer_org(
    migrated_database: None,
    money_path_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An org admin raises a dispute; its refund settles the org-payer transaction.

    ``create_org_dispute`` opens the dispute on the org-funded Milestone; a
    refund resolution settles against the same funding transaction, which carries
    ``payer_org_id`` — so the refund routes back to the organization.
    """
    del migrated_database, money_path_state
    _patch_notifications(monkeypatch)
    org = await _seed_org(prefix="refundorg")
    contributor_id = await _create_user("refundorg-contrib", ["contributor"])
    seed = await _seed_org_project(
        org_id=org["org_id"],
        contributor_id=contributor_id,
        milestone_status="funded",
        project_status="in_progress",
        with_escrow=True,
    )

    async with async_session_factory() as db:
        dispute = await dispute_service.create_org_dispute(
            db=db,
            org_id=org["org_id"],
            actor_id=org["admin_id"],
            project_id=seed["project_id"],
            payload=DisputeCreateRequest(
                milestone_id=seed["milestone_id"],
                reason="Submitted work does not match the agreed scope here.",
            ),
        )
    assert dispute.raised_by == org["admin_id"]

    # Settle the dispute as a refund via the shared escrow service; the funding
    # transaction it refunds is the org-payer transaction.
    async with async_session_factory() as db:
        async with db.begin():
            await escrow_service.refund(
                db,
                escrow_id=seed["escrow_id"],
                actor_id=org["admin_id"],
                reason="dispute_refund",
                admin_override=True,
            )

    async with async_session_factory() as session:
        escrow = await session.get(Escrow, seed["escrow_id"])
        transaction = await session.scalar(
            select(Transaction).where(Transaction.ref_id == seed["milestone_id"])
        )
    assert escrow is not None and escrow.status == "refunded"
    assert transaction is not None and transaction.status == "refunded"
    # The refunded transaction is the org-payer transaction: funds route to the org.
    assert transaction.payer_id is None
    assert transaction.payer_org_id == org["org_id"]


async def test_admin_dispute_queue_surfaces_org_operated_and_org_contributor_dispute(
    migrated_database: None,
    money_path_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Org-side disputes appear in the platform Admin queue with org names.

    Regression for the admin queue's inner joins on ``Project.operator_id`` and
    ``Proposal.contributor_id``: when both sides are organizations those columns
    are NULL, so an inner join dropped the dispute entirely. The queue must
    outer-join both sides and resolve the display name from the organization.
    """
    del migrated_database, money_path_state
    _patch_notifications(monkeypatch)
    operator_org = await _seed_org(prefix="adminq-op")
    contributor_org = await _seed_org(prefix="adminq-con")
    seed = await _seed_org_project(
        org_id=operator_org["org_id"],
        contributor_id=None,
        contributor_org_id=contributor_org["org_id"],
        milestone_status="funded",
        project_status="in_progress",
        with_escrow=True,
    )

    async with async_session_factory() as db:
        dispute = await dispute_service.create_org_dispute(
            db=db,
            org_id=operator_org["org_id"],
            actor_id=operator_org["admin_id"],
            project_id=seed["project_id"],
            payload=DisputeCreateRequest(
                milestone_id=seed["milestone_id"],
                reason="Submitted work does not match the agreed scope here.",
            ),
        )
    dispute_id = dispute.id

    async with async_session_factory() as db:
        queue = await dispute_service.list_disputes_for_admin(db=db)

    listed = next(row for row in queue.disputes if row.id == dispute_id)
    assert listed.operator_name == "adminq-op"
    assert listed.contributor_name == "adminq-con"
    assert listed.escrow_amount == Decimal("1500.00")
    # The operator-side org admin raised it, so the role reads operator and the
    # name resolves to that admin, not the org.
    assert listed.raised_by_role == "operator"
    assert listed.raised_by_name == "adminq-op-admin"


async def test_escrow_split_preserves_org_payer_and_payee_attribution(
    migrated_database: None,
    money_path_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Splitting an org-funded escrow must not null out the org XOR columns.

    The funding ``Transaction`` for an org-operated Project has
    ``payer_id=None`` / ``payer_org_id=<org>`` (BR enforced by
    ``ck_transactions_payer_xor``). ``escrow_service.split`` builds two new
    ``Transaction`` rows (release + refund); both must carry the source
    row's ``payer_org_id`` (and the release row the ``payee_org_id``) or the
    flush raises ``IntegrityError`` — after the Stripe refund has already
    fired, leaving escrow and Stripe state mismatched.
    """
    del migrated_database, money_path_state
    org = await _seed_org(prefix="splitorg")
    contributor_org = await _seed_org(prefix="splitcontrib")
    seed = await _seed_org_project(
        org_id=org["org_id"],
        contributor_id=None,
        contributor_org_id=contributor_org["org_id"],
        milestone_status="funded",
        project_status="in_progress",
        with_escrow=True,
    )

    async def fake_create_refund(
        *,
        payment_intent_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> FakeStripeRefund:
        """Stub the Stripe refund portion of a split resolution."""
        return FakeStripeRefund("re_org_split_unit")

    monkeypatch.setattr(escrow_service.stripe, "create_refund", fake_create_refund)

    async with async_session_factory() as db:
        async with db.begin():
            await escrow_service.split(
                db,
                escrow_id=seed["escrow_id"],
                actor_id=org["admin_id"],
                release_amount=Decimal("900.00"),
                refund_amount=Decimal("600.00"),
                reason="dispute_split",
                admin_override=True,
            )

    async with async_session_factory() as session:
        transactions = (
            (
                await session.execute(
                    select(Transaction)
                    .where(Transaction.ref_id == seed["milestone_id"])
                    .order_by(Transaction.created_at)
                )
            )
            .scalars()
            .all()
        )

    # Original funding row, plus the release and refund rows created by split.
    assert len(transactions) == 3
    release_row = next(t for t in transactions if t.transaction_type == "milestone")
    refund_row = next(t for t in transactions if t.transaction_type == "refund")

    assert release_row.payer_id is None
    assert release_row.payer_org_id == org["org_id"]
    assert release_row.payee_id is None
    assert release_row.payee_org_id == contributor_org["org_id"]

    assert refund_row.payer_id is None
    assert refund_row.payer_org_id == org["org_id"]
    assert refund_row.payee_id is None
    assert refund_row.payee_org_id is None
