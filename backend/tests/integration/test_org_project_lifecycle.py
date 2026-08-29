"""Integration tests for the organization Project money path (Task 7).

Covers the org-operated Project accept, fund, approve, and dispute endpoints
under ``/v1/orgs/{org_id}/...``: the full accept -> fund -> approve -> Escrow
release lifecycle plus authentication, org-role (member) and cross-org access
guards for each money endpoint.

Maps to: Task 7 in docs/superpowers/specs/2026-07-10-org-operator-design.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token
from app.integrations.paystack import PaystackInitializedTransaction
from app.modules.auth.models import User
from app.modules.financials.models import Escrow, Transaction
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.modules.projects import milestone_service
from app.modules.projects.models import (
    Deliverable,
    Dispute,
    Milestone,
    Project,
    Proposal,
)
from app.modules.workspace.models import WorkspaceMessage, WorkspaceUploadSession
from app.shared.models.audit_log import AuditLog
from tests.integration.test_org_proposal_endpoints import (
    _project_payload,
    create_user_with_roles,
)
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    create_org,
    migrated_database,
)
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio
__all__ = ["migrated_database"]


class FakeStripePaymentIntent:
    """Small stand-in for a Stripe PaymentIntent result."""

    def __init__(self, payment_intent_id: str, client_secret: str) -> None:
        """Store the provider intent id and browser client secret."""
        self.id = payment_intent_id
        self.client_secret = client_secret


@pytest.fixture
async def org_project_money_context() -> AsyncIterator[None]:
    """Reset Project, escrow, and org rows around org money-path tests."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete Project and financial rows in dependency order."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(WorkspaceMessage))
            await session.execute(delete(WorkspaceUploadSession))
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


async def _activate_operator_capability(org_id: str, *, status: str = "active") -> None:
    """Persist one operator capability row for an organization."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=UUID(org_id),
                    capability="operator",
                    status=status,
                )
            )


async def _set_org_customer(org_id: str, customer_id: str = "cus_org_money") -> None:
    """Attach a Stripe customer to an organization for the pay-in path."""
    async with async_session_factory() as session:
        async with session.begin():
            org = await session.get(Organization, UUID(org_id))
            assert org is not None
            org.stripe_customer_id = customer_id


def _contributor_proposal_payload() -> dict[str, Any]:
    """Return a valid individual-Contributor Proposal payload of budget 1500."""
    return {
        "scope": "I will deliver the procurement model and rollout plan.",
        "budget": "1500.00",
        "currency": "USD",
        "timeline_days": 21,
        "deliverables": [
            {"name": "Operating model", "description": "Documented model"}
        ],
    }


async def _create_org_operated_project(
    client: AsyncClient,
    *,
    org_prefix: str,
) -> dict[str, Any]:
    """Create an operator-capable org, its Project, and an owner/admin/member.

    The Project is posted by the org owner. An individual Contributor bids on it
    so an org admin can later accept, fund, and approve through the org money
    path.
    """
    owner_id = await create_user_with_roles(f"{org_prefix}-owner", [])
    admin_id = await create_user_with_roles(f"{org_prefix}-admin", [])
    member_id = await create_user_with_roles(f"{org_prefix}-member", [])
    contributor_id = await create_user_with_roles(
        f"{org_prefix}-contributor", ["contributor"]
    )
    owner_token = create_access_token(owner_id, [])

    org = await create_org(client, owner_token, org_prefix)
    await add_member(str(org["id"]), admin_id, "admin")
    await add_member(str(org["id"]), member_id, "member")
    await _activate_operator_capability(str(org["id"]))
    await _set_org_customer(str(org["id"]))

    created = await client.post(
        f"/v1/orgs/{org['id']}/projects",
        headers=auth(owner_token),
        json=_project_payload(),
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    proposed = await client.post(
        f"/v1/projects/{project_id}/proposals",
        headers=auth(create_access_token(contributor_id, ["contributor"])),
        json=_contributor_proposal_payload(),
    )
    assert proposed.status_code == 201

    return {
        "org_id": str(org["id"]),
        "owner_id": owner_id,
        "owner_token": owner_token,
        "admin_id": admin_id,
        "admin_token": create_access_token(admin_id, []),
        "member_id": member_id,
        "member_token": create_access_token(member_id, []),
        "contributor_id": contributor_id,
        "contributor_token": create_access_token(contributor_id, ["contributor"]),
        "project_id": project_id,
        "proposal_id": proposed.json()["id"],
    }



async def _seed_workspace_upload(
    *,
    project_id: str,
    user_id,
    s3_key: str,
) -> None:
    """Register one workspace upload session so a Deliverable may cite its key.

    Deliverable submission rejects keys without a matching session (they would
    otherwise let a Contributor presign any object in the artifacts bucket).
    """
    from uuid import UUID as _UUID

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                WorkspaceUploadSession(
                    project_id=_UUID(str(project_id)),
                    user_id=user_id,
                    s3_key=s3_key,
                    content_type="application/pdf",
                    size_limit=10_000_000,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )

async def _finalize_org_milestone_plan(
    client: AsyncClient,
    *,
    project_id: str,
    contributor_headers: Mapping[str, str],
) -> str:
    """Create and finalize a single Milestone plan matching the Proposal budget."""
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
    assert milestone.status_code == 201
    finalized = await client.post(
        f"/v1/projects/{project_id}/milestones/finalize",
        headers=contributor_headers,
    )
    assert finalized.status_code == 200
    return str(milestone.json()["id"])


async def _complete_org_funding(
    *,
    project_id: str,
    milestone_id: str,
) -> None:
    """Simulate the funding webhook: hold Escrow and mark the Milestone funded.

    Uses the transaction stamped by the fund endpoint (which carries
    ``payer_org_id``) and creates the held Escrow the deliverable-approval path
    later releases, mirroring ``escrow_service.hold`` on webhook receipt.
    """
    async with async_session_factory() as session:
        async with session.begin():
            transaction = await session.scalar(
                select(Transaction).where(
                    Transaction.ref_id == UUID(milestone_id),
                    Transaction.ref_type == "project_milestone",
                )
            )
            assert transaction is not None
            transaction.status = "completed"
            transaction.provider_ref = transaction.provider_ref or "pi_org_money"
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
                },
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            milestone = await session.get(Milestone, UUID(milestone_id))
            project = await session.get(Project, UUID(project_id))
            assert milestone is not None and project is not None
            milestone.status = "funded"
            milestone.funded_at = datetime.now(UTC)
            milestone.escrow_id = escrow.id
            project.status = "in_progress"


async def _mark_deliverable_scanned(deliverable_id: str) -> None:
    """Mark a Deliverable's files scan-clean so approval is not blocked."""
    async with async_session_factory() as session:
        async with session.begin():
            deliverable = await session.get(Deliverable, UUID(deliverable_id))
            assert deliverable is not None
            deliverable.scan_status = "visible"


def _patch_payment_intent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Patch the Stripe PaymentIntent creation and capture its call args."""
    calls: list[dict[str, Any]] = []

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: Mapping[str, str],
        idempotency_key: str | None = None,
    ) -> FakeStripePaymentIntent:
        calls.append(
            {
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency,
                "metadata": dict(metadata),
            }
        )
        return FakeStripePaymentIntent("pi_org_money", "pi_org_secret")

    monkeypatch.setattr(
        milestone_service.stripe, "create_payment_intent", fake_create_payment_intent
    )
    return calls


async def test_org_project_lifecycle_accept_fund_approve_releases_escrow(
    client: AsyncClient,
    migrated_database: None,
    org_project_money_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The org money path assigns, funds, and approves, releasing Escrow.

    Accept assigns the Project, funding stamps ``payer_org_id`` and charges the
    org Stripe customer, and approval releases the held Escrow to the individual
    Contributor beneficiary.
    """
    del migrated_database, org_project_money_context
    calls = _patch_payment_intent(monkeypatch)
    ctx = await _create_org_operated_project(client, org_prefix="lifecycle")
    org_id = ctx["org_id"]
    project_id = ctx["project_id"]
    contributor_headers = auth(ctx["contributor_token"])

    accepted = await client.post(
        f"/v1/orgs/{org_id}/projects/{project_id}/proposals/"
        f"{ctx['proposal_id']}/accept",
        headers=auth(ctx["admin_token"]),
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "assigned"

    milestone_id = await _finalize_org_milestone_plan(
        client, project_id=project_id, contributor_headers=contributor_headers
    )

    funded = await client.post(
        f"/v1/orgs/{org_id}/projects/{project_id}/milestones/{milestone_id}/fund",
        headers=auth(ctx["admin_token"]),
    )
    assert funded.status_code == 200
    assert funded.json()["client_secret"] == "pi_org_secret"
    # The org Stripe customer was charged, and funding carried the org payer id.
    assert calls[0]["customer_id"] == "cus_org_money"
    assert calls[0]["metadata"]["payer_org_id"] == org_id

    async with async_session_factory() as session:
        transaction = await session.scalar(
            select(Transaction).where(
                Transaction.ref_id == UUID(milestone_id),
                Transaction.ref_type == "project_milestone",
            )
        )
    assert transaction is not None
    assert transaction.payer_id is None
    assert transaction.payer_org_id == UUID(org_id)

    await _complete_org_funding(project_id=project_id, milestone_id=milestone_id)

    await _seed_workspace_upload(
        project_id=project_id,
        user_id=ctx["contributor_id"],
        s3_key="workspace/project/final.pdf",
    )
    submitted = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables",
        headers=contributor_headers,
        json={
            "name": "Final playbook",
            "description": "Implementation playbook.",
            "file_keys": ["workspace/project/final.pdf"],
        },
    )
    assert submitted.status_code == 201
    deliverable_id = submitted.json()["id"]
    await _mark_deliverable_scanned(deliverable_id)

    approved = await client.post(
        f"/v1/orgs/{org_id}/projects/{project_id}/deliverables/"
        f"{deliverable_id}/approve",
        headers=auth(ctx["admin_token"]),
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    async with async_session_factory() as session:
        escrow = await session.scalar(
            select(Escrow).where(Escrow.ref_id == UUID(milestone_id))
        )
        released_transaction = await session.scalar(
            select(Transaction).where(
                Transaction.ref_id == UUID(milestone_id),
                Transaction.ref_type == "project_milestone",
            )
        )
    assert escrow is not None and escrow.status == "released"
    # Escrow release credits the individual Contributor beneficiary; the org
    # remains the payer.
    assert released_transaction is not None
    assert released_transaction.payee_id == ctx["contributor_id"]
    assert released_transaction.payer_org_id == UUID(org_id)


async def test_org_admin_can_list_incoming_project_proposals(
    client: AsyncClient,
    migrated_database: None,
    org_project_money_context: None,
) -> None:
    """An org admin can review proposals submitted to its operated Project."""
    del migrated_database, org_project_money_context
    ctx = await _create_org_operated_project(client, org_prefix="proposal-inbox")

    response = await client.get(
        f"/v1/orgs/{ctx['org_id']}/projects/{ctx['project_id']}/proposals",
        headers=auth(ctx["admin_token"]),
    )

    assert response.status_code == 200
    proposals = response.json()["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["id"] == ctx["proposal_id"]
    assert proposals[0]["contributor_name"] is not None


async def test_org_milestone_funding_routes_to_paystack_for_nigerian_billing(
    client: AsyncClient,
    migrated_database: None,
    org_project_money_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Nigerian org funds a Milestone through Paystack hosted checkout.

    No org Stripe customer is required on this rail: the charge is
    initialized against the org's billing contact (falling back to the
    owner) and the response carries the redirect URL instead of a client
    secret. Enforces FR-FIN-005 for org Operators on the pilot corridor.
    """
    del migrated_database, org_project_money_context
    paystack_calls: list[dict[str, Any]] = []

    async def fail_payment_intent(**kwargs: Any) -> Any:
        """Fail the test if the Paystack rail touches Stripe."""
        raise AssertionError("Stripe intent must not be created on Paystack rail")

    async def fake_initialize_transaction(
        *,
        email: str,
        amount: Decimal,
        currency: str,
        metadata: dict[str, str],
        callback_url: str | None = None,
    ) -> PaystackInitializedTransaction:
        """Record the Paystack charge initialization for org funding."""
        paystack_calls.append(
            {
                "email": email,
                "amount": amount,
                "currency": currency,
                "metadata": dict(metadata),
            }
        )
        return PaystackInitializedTransaction(
            reference="auracles_org_milestone_ref_001",
            authorization_url="https://checkout.paystack.com/org_milestone_001",
            access_code="access_org_milestone_001",
        )

    monkeypatch.setattr(
        milestone_service.stripe,
        "create_payment_intent",
        fail_payment_intent,
    )
    monkeypatch.setattr(
        milestone_service.paystack,
        "initialize_transaction",
        fake_initialize_transaction,
    )
    ctx = await _create_org_operated_project(client, org_prefix="ngn-fund")
    org_id = ctx["org_id"]
    project_id = ctx["project_id"]
    contributor_headers = auth(ctx["contributor_token"])

    accepted = await client.post(
        f"/v1/orgs/{org_id}/projects/{project_id}/proposals/"
        f"{ctx['proposal_id']}/accept",
        headers=auth(ctx["admin_token"]),
    )
    assert accepted.status_code == 200
    milestone_id = await _finalize_org_milestone_plan(
        client, project_id=project_id, contributor_headers=contributor_headers
    )

    funded = await client.post(
        f"/v1/orgs/{org_id}/projects/{project_id}/milestones/{milestone_id}/fund",
        headers=auth(ctx["admin_token"]),
        json={"country": "NG"},
    )

    async with async_session_factory() as session:
        transaction = await session.scalar(
            select(Transaction).where(
                Transaction.ref_id == UUID(milestone_id),
                Transaction.ref_type == "project_milestone",
            )
        )
        owner = await session.get(User, UUID(str(ctx["owner_id"])))

    assert funded.status_code == 200
    body = funded.json()
    assert body["provider"] == "paystack"
    assert body["authorization_url"] == (
        "https://checkout.paystack.com/org_milestone_001"
    )
    assert body["client_secret"] is None
    assert transaction is not None
    assert transaction.payer_id is None
    assert transaction.payer_org_id == UUID(org_id)
    assert transaction.provider == "paystack"
    assert transaction.provider_ref == "auracles_org_milestone_ref_001"
    assert owner is not None
    initialized = paystack_calls[0]
    # No billing_email is configured, so the charge bills the org owner.
    assert initialized["email"] == owner.email
    assert initialized["metadata"]["kind"] == "escrow"
    assert initialized["metadata"]["transaction_id"] == str(transaction.id)
    assert initialized["metadata"]["payer_org_id"] == org_id


async def test_org_admin_can_cancel_unfunded_project_acceptance(
    client: AsyncClient,
    migrated_database: None,
    org_project_money_context: None,
) -> None:
    """An org admin can reopen its assigned Project before escrow funding."""
    del migrated_database, org_project_money_context
    ctx = await _create_org_operated_project(client, org_prefix="cancel-acceptance")
    accepted = await client.post(
        f"/v1/orgs/{ctx['org_id']}/projects/{ctx['project_id']}/proposals/"
        f"{ctx['proposal_id']}/accept",
        headers=auth(ctx["admin_token"]),
    )
    assert accepted.status_code == 200

    cancelled = await client.post(
        f"/v1/orgs/{ctx['org_id']}/projects/{ctx['project_id']}/cancel-acceptance",
        headers=auth(ctx["admin_token"]),
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "open"
    assert cancelled.json()["accepted_proposal_id"] is None


async def test_org_accept_endpoint_auth_and_rbac(
    client: AsyncClient,
    migrated_database: None,
    org_project_money_context: None,
) -> None:
    """Accept is authenticated, admin-only, and org-scoped."""
    del migrated_database, org_project_money_context
    ctx = await _create_org_operated_project(client, org_prefix="accept-rbac")
    org_id = ctx["org_id"]
    path = (
        f"/v1/orgs/{org_id}/projects/{ctx['project_id']}/proposals/"
        f"{ctx['proposal_id']}/accept"
    )

    unauth = await client.post(path)
    assert unauth.status_code == 401

    member = await client.post(path, headers=auth(ctx["member_token"]))
    assert member.status_code == 403

    other = await _create_org_operated_project(client, org_prefix="accept-other")
    cross = await client.post(
        f"/v1/orgs/{other['org_id']}/projects/{ctx['project_id']}/proposals/"
        f"{ctx['proposal_id']}/accept",
        headers=auth(other["admin_token"]),
    )
    assert cross.status_code == 404


async def test_org_fund_endpoint_auth_and_rbac(
    client: AsyncClient,
    migrated_database: None,
    org_project_money_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fund is authenticated, admin-only, and org-scoped."""
    del migrated_database, org_project_money_context
    _patch_payment_intent(monkeypatch)
    ctx = await _create_org_operated_project(client, org_prefix="fund-rbac")
    org_id = ctx["org_id"]
    project_id = ctx["project_id"]
    await client.post(
        f"/v1/orgs/{org_id}/projects/{project_id}/proposals/"
        f"{ctx['proposal_id']}/accept",
        headers=auth(ctx["admin_token"]),
    )
    milestone_id = await _finalize_org_milestone_plan(
        client,
        project_id=project_id,
        contributor_headers=auth(ctx["contributor_token"]),
    )
    path = f"/v1/orgs/{org_id}/projects/{project_id}/milestones/{milestone_id}/fund"

    unauth = await client.post(path)
    assert unauth.status_code == 401

    member = await client.post(path, headers=auth(ctx["member_token"]))
    assert member.status_code == 403

    other = await _create_org_operated_project(client, org_prefix="fund-other")
    cross = await client.post(
        f"/v1/orgs/{other['org_id']}/projects/{project_id}/milestones/"
        f"{milestone_id}/fund",
        headers=auth(other["admin_token"]),
    )
    assert cross.status_code == 404

    happy = await client.post(path, headers=auth(ctx["admin_token"]))
    assert happy.status_code == 200


async def test_org_approve_endpoint_auth_and_rbac(
    client: AsyncClient,
    migrated_database: None,
    org_project_money_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approve is authenticated, admin-only, and org-scoped."""
    del migrated_database, org_project_money_context
    _patch_payment_intent(monkeypatch)
    ctx = await _create_org_operated_project(client, org_prefix="approve-rbac")
    org_id = ctx["org_id"]
    project_id = ctx["project_id"]
    contributor_headers = auth(ctx["contributor_token"])
    await client.post(
        f"/v1/orgs/{org_id}/projects/{project_id}/proposals/"
        f"{ctx['proposal_id']}/accept",
        headers=auth(ctx["admin_token"]),
    )
    milestone_id = await _finalize_org_milestone_plan(
        client, project_id=project_id, contributor_headers=contributor_headers
    )
    await client.post(
        f"/v1/orgs/{org_id}/projects/{project_id}/milestones/{milestone_id}/fund",
        headers=auth(ctx["admin_token"]),
    )
    await _complete_org_funding(project_id=project_id, milestone_id=milestone_id)
    await _seed_workspace_upload(
        project_id=project_id,
        user_id=ctx["contributor_id"],
        s3_key="workspace/project/final.pdf",
    )
    submitted = await client.post(
        f"/v1/projects/{project_id}/milestones/{milestone_id}/deliverables",
        headers=contributor_headers,
        json={
            "name": "Final",
            "description": "Work.",
            "file_keys": ["workspace/project/final.pdf"],
        },
    )
    deliverable_id = submitted.json()["id"]
    await _mark_deliverable_scanned(deliverable_id)
    path = (
        f"/v1/orgs/{org_id}/projects/{project_id}/deliverables/"
        f"{deliverable_id}/approve"
    )

    unauth = await client.post(path)
    assert unauth.status_code == 401

    member = await client.post(path, headers=auth(ctx["member_token"]))
    assert member.status_code == 403

    other = await _create_org_operated_project(client, org_prefix="approve-other")
    cross = await client.post(
        f"/v1/orgs/{other['org_id']}/projects/{project_id}/deliverables/"
        f"{deliverable_id}/approve",
        headers=auth(other["admin_token"]),
    )
    assert cross.status_code == 404

    happy = await client.post(path, headers=auth(ctx["admin_token"]))
    assert happy.status_code == 200


async def test_org_dispute_endpoint_happy_and_rbac(
    client: AsyncClient,
    migrated_database: None,
    org_project_money_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raising a dispute is authenticated, admin-only, org-scoped, and works."""
    del migrated_database, org_project_money_context
    _patch_payment_intent(monkeypatch)
    ctx = await _create_org_operated_project(client, org_prefix="dispute-rbac")
    org_id = ctx["org_id"]
    project_id = ctx["project_id"]
    await client.post(
        f"/v1/orgs/{org_id}/projects/{project_id}/proposals/"
        f"{ctx['proposal_id']}/accept",
        headers=auth(ctx["admin_token"]),
    )
    milestone_id = await _finalize_org_milestone_plan(
        client,
        project_id=project_id,
        contributor_headers=auth(ctx["contributor_token"]),
    )
    await client.post(
        f"/v1/orgs/{org_id}/projects/{project_id}/milestones/{milestone_id}/fund",
        headers=auth(ctx["admin_token"]),
    )
    await _complete_org_funding(project_id=project_id, milestone_id=milestone_id)
    path = f"/v1/orgs/{org_id}/projects/{project_id}/disputes"
    body = {"milestone_id": milestone_id, "reason": "Work does not match scope here."}

    unauth = await client.post(path, json=body)
    assert unauth.status_code == 401

    member = await client.post(path, headers=auth(ctx["member_token"]), json=body)
    assert member.status_code == 403

    other = await _create_org_operated_project(client, org_prefix="dispute-other")
    cross = await client.post(
        f"/v1/orgs/{other['org_id']}/projects/{project_id}/disputes",
        headers=auth(other["admin_token"]),
        json=body,
    )
    assert cross.status_code == 404

    happy = await client.post(path, headers=auth(ctx["admin_token"]), json=body)
    assert happy.status_code == 201
    assert happy.json()["status"] == "open"
