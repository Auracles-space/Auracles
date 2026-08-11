"""Integration tests for Stripe webhook ingestion and dispatch."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.integrations.stripe import StripeProviderError
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
)
from app.modules.auth.models import User, UserRole
from app.modules.collections.models import (
    CollectionEarningAllocation,
    CollectionFramework,
    CollectionPurchaseSnapshot,
    FrameworkCollection,
)
from app.modules.collections.purchase import (
    CollectionPurchaseProcessingError,
    confirm_collection_purchase,
)
from app.modules.developer.models import (
    ApiKey,
    DeveloperAccount,
    DeveloperApplication,
    PartnerCommission,
    PartnerPurchaseAttribution,
)
from app.modules.financials.models import (
    Escrow,
    FinancialEvent,
    Payout,
    PayoutAccount,
    Transaction,
)
from app.modules.frameworks.models import Framework, License
from app.modules.projects.models import Milestone, Project, Proposal
from app.modules.webhooks import service as webhook_service
from app.modules.webhooks.models import WebhookEvent
from app.modules.workspace.models import WorkspaceMessage
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async


class FakeInvoiceTask:
    """Celery task double that records invoice generation requests."""

    def __init__(self) -> None:
        """Initialise the in-memory dispatch log."""
        self.dispatched: list[str] = []

    def delay(self, transaction_id: str) -> None:
        """Record the transaction id that would be sent to Celery."""
        self.dispatched.append(transaction_id)


async def reset_webhook_state() -> None:
    """Remove webhook test data in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(WebhookEvent))
        await session.execute(delete(FinancialEvent))
        await session.execute(delete(AuditLog))
        await session.execute(delete(PartnerCommission))
        await session.execute(delete(PartnerPurchaseAttribution))
        await session.execute(delete(CollectionEarningAllocation))
        await session.execute(delete(CollectionPurchaseSnapshot))
        await session.execute(delete(Payout))
        await session.execute(delete(PayoutAccount))
        await session.execute(delete(WorkspaceMessage))
        await session.execute(delete(AttestationUploadSession))
        await session.execute(delete(AttestationOffer))
        await session.execute(delete(AttestationDispute))
        await session.execute(delete(Attestation))
        await session.execute(delete(Milestone))
        await session.execute(delete(Escrow))
        await session.execute(delete(License))
        await session.execute(delete(CollectionFramework))
        await session.execute(delete(ApiKey))
        await session.execute(delete(FrameworkCollection))
        await session.execute(delete(DeveloperAccount))
        await session.execute(delete(DeveloperApplication))
        await session.execute(delete(Transaction))
        await session.execute(delete(Framework))
        await session.execute(delete(Project))
        await session.execute(delete(Proposal))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
async def webhook_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state and install a controllable Stripe verifier double."""
    await engine.dispose()
    await reset_webhook_state()
    fake_invoice_task = FakeInvoiceTask()
    context: dict[str, Any] = {
        "event": None,
        "verified_payloads": [],
        "invoice_task": fake_invoice_task,
    }

    def fake_verify_webhook(
        payload: bytes,
        signature_header: str | None,
    ) -> dict[str, Any]:
        """Record raw body verification and return the configured event."""
        context["verified_payloads"].append(
            {"payload": payload, "signature": signature_header}
        )
        if signature_header == "bad-signature":
            raise StripeProviderError("bad signature")
        event = context["event"]
        if not isinstance(event, dict):
            raise StripeProviderError("missing test event")
        return event

    monkeypatch.setattr(
        webhook_service.stripe,
        "verify_webhook",
        fake_verify_webhook,
    )
    monkeypatch.setattr(
        webhook_service,
        "generate_invoice_pdf",
        fake_invoice_task,
        raising=False,
    )
    try:
        yield context
    finally:
        await reset_webhook_state()
        await engine.dispose()


async def create_user_with_roles(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash="not-used",
                display_name=email.split("@")[0],
                email_verified=True,
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


async def create_pending_purchase() -> tuple[UUID, UUID, UUID, UUID]:
    """Create a pending purchase transaction that a webhook can complete."""
    contributor_id = await create_user_with_roles(
        "webhook-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "webhook-operator@auracles.space",
        ["operator"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Webhook Purchase Framework",
                description="Framework used by Stripe webhook tests.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["stripe", "webhook"],
                price=Decimal("149.00"),
                currency="USD",
                license_types=["single_user", "team", "organizational"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("149.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("149.00"),
                transaction_type="purchase",
                status="pending",
                provider="stripe",
                provider_ref="pi_webhook_123",
                ref_id=framework.id,
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id, framework.id, operator_id, contributor_id


async def create_pending_collection_purchase() -> tuple[
    UUID,
    UUID,
    UUID,
    UUID,
    UUID,
]:
    """Create a pending Collection purchase with one prior-owned member."""
    contributor_id = await create_user_with_roles(
        "collection-webhook-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "collection-webhook-operator@auracles.space",
        ["operator"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            first_framework = Framework(
                contributor_id=contributor_id,
                title="Collection Prior-Owned Framework",
                description="Framework already owned before bundle checkout.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["stripe", "collection"],
                price=Decimal("400.00"),
                currency="USD",
                license_types=["single_user", "team"],
                published_at=datetime.now(UTC),
            )
            second_framework = Framework(
                contributor_id=contributor_id,
                title="Collection Minted Framework",
                description="Framework minted by bundle checkout.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["stripe", "collection"],
                price=Decimal("500.00"),
                currency="USD",
                license_types=["single_user", "team"],
                published_at=datetime.now(UTC),
            )
            session.add_all([first_framework, second_framework])
            await session.flush()
            collection = FrameworkCollection(
                contributor_id=contributor_id,
                title="Webhook Collection Bundle",
                description="Bundle used by Stripe webhook tests.",
                bundle_price=Decimal("700.00"),
                currency="USD",
                status="published",
            )
            session.add(collection)
            await session.flush()
            session.add_all(
                [
                    CollectionFramework(
                        collection_id=collection.id,
                        framework_id=first_framework.id,
                    ),
                    CollectionFramework(
                        collection_id=collection.id,
                        framework_id=second_framework.id,
                    ),
                ]
            )
            prior_license = License(
                framework_id=first_framework.id,
                operator_id=operator_id,
                license_type="team",
                status="active",
                version_at_grant="1.0.0",
            )
            session.add(prior_license)
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("700.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("700.00"),
                transaction_type="purchase",
                status="pending",
                provider="stripe",
                provider_ref="pi_collection_webhook_123",
                ref_id=collection.id,
                ref_type="collection",
            )
            session.add(transaction)
            await session.flush()
            session.add_all(
                [
                    CollectionPurchaseSnapshot(
                        transaction_id=transaction.id,
                        collection_id=collection.id,
                        framework_id=first_framework.id,
                        list_price_at_purchase=Decimal("400.00"),
                        license_type="team",
                        already_owned=True,
                    ),
                    CollectionPurchaseSnapshot(
                        transaction_id=transaction.id,
                        collection_id=collection.id,
                        framework_id=second_framework.id,
                        list_price_at_purchase=Decimal("500.00"),
                        license_type="team",
                        already_owned=False,
                    ),
                ]
            )
            await session.flush()
            return (
                transaction.id,
                collection.id,
                first_framework.id,
                second_framework.id,
                operator_id,
            )


async def create_partner_attribution(
    *,
    transaction_id: UUID,
    framework_id: UUID,
    buyer_user_id: UUID,
    tier_rate: Decimal = Decimal("0.0800"),
) -> UUID:
    """Create a Developer account, API key, and purchase attribution row."""
    developer_id = await create_user_with_roles(
        "webhook-developer@auracles.space",
        ["developer"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            application = DeveloperApplication(
                user_id=developer_id,
                company_name="Webhook Partner",
                website="https://webhook-partner.example.com",
                use_case="Attribute purchase webhooks to partner commissions.",
                status="approved",
                reviewed_at=datetime.now(UTC),
            )
            session.add(application)
            await session.flush()
            account = DeveloperAccount(
                user_id=developer_id,
                application_id=application.id,
                company_name=application.company_name,
                commission_tier=2,
                tier_rate=tier_rate,
            )
            session.add(account)
            await session.flush()
            api_key = ApiKey(
                developer_account_id=account.id,
                name="Webhook attribution key",
                key_prefix="ak_webhook",
                key_hash="webhook-test-hash",
                scopes=["purchase:write"],
            )
            session.add(api_key)
            await session.flush()
            attribution = PartnerPurchaseAttribution(
                api_key_id=api_key.id,
                developer_account_id=account.id,
                transaction_id=transaction_id,
                framework_id=framework_id,
                buyer_user_id=buyer_user_id,
                license_type="team",
                tier_at_sale=2,
                tier_rate=tier_rate,
            )
            session.add(attribution)
            await session.flush()
            return api_key.id


async def create_pending_escrow_transaction() -> tuple[UUID, UUID, UUID]:
    """Create a pending milestone funding transaction for escrow webhook tests."""
    operator_id = await create_user_with_roles(
        "escrow-operator@auracles.space",
        ["operator"],
    )
    contributor_id = await create_user_with_roles(
        "escrow-contributor@auracles.space",
        ["contributor"],
    )
    milestone_id = UUID("00000000-0000-4000-8000-000000000001")
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("1250.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("1250.00"),
                transaction_type="milestone",
                status="pending",
                provider="stripe",
                provider_ref="pi_escrow_123",
                ref_id=milestone_id,
                ref_type="project_milestone",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id, milestone_id, operator_id


async def create_pending_attestation_fee_transaction(
    *,
    email: str = "attestation-escrow-operator@auracles.space",
    provider_ref: str = "pi_attestation_escrow_123",
) -> tuple[UUID, UUID, UUID]:
    """Create a pending Attestation fee transaction for escrow webhook tests."""
    operator_id = await create_user_with_roles(email, ["operator"])
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="operator",
                target_id=operator_id,
                requestor_id=operator_id,
                status="pending_fee",
                requested_specializations=["operations"],
                requested_jurisdictions=["US"],
                fee_amount=Decimal("300.00"),
                currency="USD",
            )
            session.add(attestation)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=None,
                amount=Decimal("300.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("300.00"),
                transaction_type="attestation_fee",
                status="pending",
                provider="stripe",
                provider_ref=provider_ref,
                ref_id=attestation.id,
                ref_type="attestation",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id, attestation.id, operator_id


async def create_pending_project_milestone_transaction() -> tuple[
    UUID,
    UUID,
    UUID,
    UUID,
]:
    """Create a finalized Project Milestone and pending funding transaction."""
    operator_id = await create_user_with_roles(
        "project-escrow-operator@auracles.space",
        ["operator"],
    )
    contributor_id = await create_user_with_roles(
        "project-escrow-contributor@auracles.space",
        ["contributor"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            project = Project(
                operator_id=operator_id,
                title="Webhook Funded Project",
                description="Project used by webhook milestone funding tests.",
                category="operations",
                required_deliverables=[
                    {"name": "Playbook", "description": "Implementation playbook"}
                ],
                budget_min=Decimal("1500.00"),
                budget_max=Decimal("1500.00"),
                currency="USD",
                status="assigned",
                milestone_plan_status="finalized",
                expires_at=datetime.now(UTC),
            )
            session.add(project)
            await session.flush()
            proposal = Proposal(
                project_id=project.id,
                contributor_id=contributor_id,
                scope="I will deliver the project implementation.",
                budget=Decimal("1500.00"),
                currency="USD",
                timeline_days=21,
                deliverables=[{"name": "Playbook", "description": "Playbook"}],
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
                description="Build the project deliverable.",
                budget=Decimal("1500.00"),
                currency="USD",
                status="pending",
            )
            session.add(milestone)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("1500.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("1500.00"),
                transaction_type="milestone",
                status="pending",
                provider="stripe",
                provider_ref="pi_project_escrow_123",
                ref_id=milestone.id,
                ref_type="project_milestone",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id, project.id, milestone.id, operator_id


def payment_intent_event(
    event_id: str,
    event_type: str,
    *,
    transaction_id: UUID,
    framework_id: UUID,
    license_type: str = "team",
    kind: str = "purchase",
    provider_ref: str = "pi_webhook_123",
    extra_metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a Stripe PaymentIntent event payload for financial webhook tests."""
    metadata = {
        "transaction_id": str(transaction_id),
        "kind": kind,
        "framework_id": str(framework_id),
        "license_type": license_type,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": provider_ref,
                "metadata": metadata,
            }
        },
    }


def collection_payment_intent_event(
    event_id: str,
    event_type: str,
    *,
    transaction_id: UUID,
    collection_id: UUID,
    provider_ref: str = "pi_collection_webhook_123",
) -> dict[str, Any]:
    """Build a Stripe PaymentIntent event payload for Collection purchases."""
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": provider_ref,
                "metadata": {
                    "transaction_id": str(transaction_id),
                    "kind": "collection",
                    "collection_id": str(collection_id),
                },
            }
        },
    }


async def test_stripe_payment_intent_success_creates_license_once(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified purchase webhook completes the transaction and grants access."""
    transaction_id, framework_id, operator_id, _ = await create_pending_purchase()
    webhook_context["event"] = payment_intent_event(
        "evt_purchase_success",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    first = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    replay = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        licenses = (
            (
                await session.execute(
                    select(License).where(License.framework_id == framework_id)
                )
            )
            .scalars()
            .all()
        )
        events = (await session.execute(select(WebhookEvent))).scalars().all()
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_completed")
        )

    assert first.status_code == 200
    assert first.json() == {"received": True, "status": "processed"}
    assert replay.status_code == 200
    assert replay.json() == {"received": True, "status": "duplicate"}
    assert transaction is not None
    assert transaction.status == "completed"
    assert len(licenses) == 1
    assert licenses[0].operator_id == operator_id
    assert licenses[0].transaction_id == transaction_id
    assert licenses[0].license_type == "team"
    assert licenses[0].seats_total == 10
    assert len(events) == 1
    assert events[0].provider_event_id == "evt_purchase_success"
    assert events[0].status == "processed"
    assert audit is not None
    assert audit.target_id == transaction_id
    invoice_task: FakeInvoiceTask = webhook_context["invoice_task"]
    assert invoice_task.dispatched == [str(transaction_id)]


async def test_stripe_collection_purchase_success_mints_missing_license_and_allocation(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified Collection webhook mints missing Licenses and allocations once."""
    (
        transaction_id,
        collection_id,
        prior_framework_id,
        minted_framework_id,
        operator_id,
    ) = await create_pending_collection_purchase()
    webhook_context["event"] = collection_payment_intent_event(
        "evt_collection_purchase_success",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        collection_id=collection_id,
    )

    first = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    replay = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        licenses = (
            (
                await session.execute(
                    select(License)
                    .where(License.operator_id == operator_id)
                    .order_by(License.framework_id)
                )
            )
            .scalars()
            .all()
        )
        allocations = (
            (
                await session.execute(
                    select(CollectionEarningAllocation).where(
                        CollectionEarningAllocation.transaction_id == transaction_id
                    )
                )
            )
            .scalars()
            .all()
        )
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "collection_purchased")
        )

    assert first.status_code == 200
    assert first.json() == {"received": True, "status": "processed"}
    assert replay.status_code == 200
    assert replay.json() == {"received": True, "status": "duplicate"}
    assert transaction is not None
    assert transaction.status == "completed"
    assert len(licenses) == 2
    prior_license = next(
        license_row
        for license_row in licenses
        if license_row.framework_id == prior_framework_id
    )
    minted_license = next(
        license_row
        for license_row in licenses
        if license_row.framework_id == minted_framework_id
    )
    assert prior_license.transaction_id is None
    assert prior_license.source == "individual"
    assert minted_license.transaction_id == transaction_id
    assert minted_license.source == "collection"
    assert minted_license.collection_id == collection_id
    assert minted_license.license_type == "team"
    assert minted_license.seats_total == 10
    assert len(allocations) == 1
    assert allocations[0].framework_id == minted_framework_id
    assert allocations[0].allocated_amount == Decimal("700.00")
    assert audit is not None
    assert audit.target_id == transaction_id
    assert audit.metadata_["collection_id"] == str(collection_id)
    assert audit.metadata_["minted_license_count"] == 1
    invoice_task: FakeInvoiceTask = webhook_context["invoice_task"]
    assert invoice_task.dispatched == [str(transaction_id)]


async def test_confirm_collection_purchase_reactivates_license_idempotently(
    webhook_context: dict[str, Any],
) -> None:
    """Collection confirmation can replay without duplicate allocations."""
    del webhook_context
    (
        transaction_id,
        collection_id,
        _prior_framework_id,
        minted_framework_id,
        operator_id,
    ) = await create_pending_collection_purchase()
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                License(
                    framework_id=minted_framework_id,
                    operator_id=operator_id,
                    license_type="single_user",
                    status="revoked",
                    version_at_grant="1.0.0",
                )
            )

    async with async_session_factory() as session:
        async with session.begin():
            first_result = await confirm_collection_purchase(
                session,
                transaction_id=transaction_id,
                payment_intent_id="pi_collection_webhook_123",
            )
    async with async_session_factory() as session:
        async with session.begin():
            replay_result = await confirm_collection_purchase(
                session,
                transaction_id=transaction_id,
                payment_intent_id="pi_collection_webhook_123",
            )

    async with async_session_factory() as session:
        licenses = (
            (
                await session.execute(
                    select(License)
                    .where(License.operator_id == operator_id)
                    .order_by(License.framework_id)
                )
            )
            .scalars()
            .all()
        )
        allocations = (
            (
                await session.execute(
                    select(CollectionEarningAllocation).where(
                        CollectionEarningAllocation.transaction_id == transaction_id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert first_result == transaction_id
    assert replay_result == transaction_id
    assert len(licenses) == 2
    reactivated = next(
        license_row
        for license_row in licenses
        if license_row.framework_id == minted_framework_id
    )
    assert reactivated.status == "active"
    assert reactivated.transaction_id == transaction_id
    assert reactivated.source == "collection"
    assert reactivated.collection_id == collection_id
    assert len(allocations) == 1
    assert allocations[0].framework_id == minted_framework_id
    assert allocations[0].allocated_amount == Decimal("700.00")


async def test_confirm_collection_purchase_rejects_unavailable_snapshot_member(
    webhook_context: dict[str, Any],
) -> None:
    """Collection confirmation fails loudly when a snapshotted member changed."""
    del webhook_context
    (
        transaction_id,
        _collection_id,
        _prior_framework_id,
        minted_framework_id,
        _operator_id,
    ) = await create_pending_collection_purchase()
    async with async_session_factory() as session:
        async with session.begin():
            framework = await session.get(Framework, minted_framework_id)
            assert framework is not None
            framework.status = "draft"

    with pytest.raises(CollectionPurchaseProcessingError) as exc_info:
        async with async_session_factory() as session:
            async with session.begin():
                await confirm_collection_purchase(
                    session,
                    transaction_id=transaction_id,
                    payment_intent_id="pi_collection_webhook_123",
                )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.scalar(
            select(License).where(License.framework_id == minted_framework_id)
        )

    assert str(exc_info.value) == "collection framework unavailable"
    assert transaction is not None
    assert transaction.status == "pending"
    assert license_row is None


async def test_confirm_collection_purchase_rejects_midflight_owned_member(
    webhook_context: dict[str, Any],
) -> None:
    """Collection confirmation fails when a missing member became licensed."""
    del webhook_context
    (
        transaction_id,
        _collection_id,
        _prior_framework_id,
        minted_framework_id,
        operator_id,
    ) = await create_pending_collection_purchase()
    async with async_session_factory() as session:
        async with session.begin():
            collection_transaction = await session.get(Transaction, transaction_id)
            assert collection_transaction is not None
            individual_transaction = Transaction(
                payer_id=operator_id,
                payee_id=collection_transaction.payee_id,
                amount=Decimal("500.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("500.00"),
                transaction_type="purchase",
                status="completed",
                provider="stripe",
                provider_ref="pi_midflight_individual_123",
                ref_id=minted_framework_id,
                ref_type="framework",
            )
            session.add(individual_transaction)
            await session.flush()
            session.add(
                License(
                    framework_id=minted_framework_id,
                    operator_id=operator_id,
                    transaction_id=individual_transaction.id,
                    source="individual",
                    license_type="team",
                    status="active",
                    version_at_grant="1.0.0",
                )
            )

    with pytest.raises(CollectionPurchaseProcessingError) as exc_info:
        async with async_session_factory() as session:
            async with session.begin():
                await confirm_collection_purchase(
                    session,
                    transaction_id=transaction_id,
                    payment_intent_id="pi_collection_webhook_123",
                )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        allocations = (
            (
                await session.execute(
                    select(CollectionEarningAllocation).where(
                        CollectionEarningAllocation.transaction_id == transaction_id
                    )
                )
            )
            .scalars()
            .all()
        )
        license_row = await session.scalar(
            select(License).where(
                License.framework_id == minted_framework_id,
                License.operator_id == operator_id,
            )
        )

    assert str(exc_info.value) == "collection member already licensed"
    assert transaction is not None
    assert transaction.status == "pending"
    assert allocations == []
    assert license_row is not None
    assert license_row.transaction_id != transaction_id
    assert license_row.source == "individual"


async def test_stripe_purchase_success_creates_partner_commission_once(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """Partner-attributed purchase success creates one pending commission."""
    transaction_id, framework_id, operator_id, _ = await create_pending_purchase()
    api_key_id = await create_partner_attribution(
        transaction_id=transaction_id,
        framework_id=framework_id,
        buyer_user_id=operator_id,
        tier_rate=Decimal("0.0800"),
    )
    webhook_context["event"] = payment_intent_event(
        "evt_partner_purchase_success",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=framework_id,
        extra_metadata={
            "api_key_id": str(api_key_id),
            "tier_rate": "0.0800",
        },
    )

    first = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    replay = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        commissions = (
            (
                await session.execute(
                    select(PartnerCommission).where(
                        PartnerCommission.transaction_id == transaction_id
                    )
                )
            )
            .scalars()
            .all()
        )
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "partner_commission_created")
        )

    assert first.status_code == 200
    assert first.json() == {"received": True, "status": "processed"}
    assert replay.status_code == 200
    assert replay.json() == {"received": True, "status": "duplicate"}
    assert len(commissions) == 1
    assert commissions[0].api_key_id == api_key_id
    assert commissions[0].framework_id == framework_id
    assert commissions[0].sale_amount == Decimal("149.00")
    assert commissions[0].tier_at_sale == 2
    assert commissions[0].tier_rate == Decimal("0.0800")
    assert commissions[0].commission_amount == Decimal("11.92")
    assert commissions[0].status == "pending"
    assert audit is not None
    assert audit.target_id == commissions[0].id


async def test_purchase_webhook_fails_duplicate_active_license_transaction(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A second purchase webhook cannot complete without granting a License."""
    (
        first_transaction_id,
        framework_id,
        operator_id,
        contributor_id,
    ) = await create_pending_purchase()
    webhook_context["event"] = payment_intent_event(
        "evt_first_purchase_success",
        "payment_intent.succeeded",
        transaction_id=first_transaction_id,
        framework_id=framework_id,
    )
    first = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        async with session.begin():
            second_transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("149.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("149.00"),
                transaction_type="purchase",
                status="pending",
                provider="stripe",
                provider_ref="pi_webhook_duplicate",
                ref_id=framework_id,
                ref_type="framework",
            )
            session.add(second_transaction)
            await session.flush()
            second_transaction_id = second_transaction.id

    webhook_context["event"] = payment_intent_event(
        "evt_duplicate_purchase_success",
        "payment_intent.succeeded",
        transaction_id=second_transaction_id,
        framework_id=framework_id,
        provider_ref="pi_webhook_duplicate",
    )
    duplicate = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        second = await session.get(Transaction, second_transaction_id)
        licenses = (
            (
                await session.execute(
                    select(License).where(License.framework_id == framework_id)
                )
            )
            .scalars()
            .all()
        )
        duplicate_event = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.provider_event_id == "evt_duplicate_purchase_success"
            )
        )

    assert first.status_code == 200
    assert duplicate.status_code == 500
    assert second is not None
    assert second.status == "pending"
    assert len(licenses) == 1
    assert duplicate_event is not None
    assert duplicate_event.status == "failed"
    assert duplicate_event.error is not None
    assert "different transaction" in duplicate_event.error


async def test_stripe_webhook_reprocesses_after_transient_failure(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A failed event must reprocess on redelivery, not be dropped as duplicate.

    Stripe retries deliver the same event id. If the first dispatch fails for a
    transient reason (here, the event arrives before its transaction row is
    committed), the durable idempotency row must not turn the retry into a
    silent no-op or money-side effects are permanently lost.
    """
    contributor_id = await create_user_with_roles(
        "retry-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "retry-operator@auracles.space",
        ["operator"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Retry Framework",
                description="Framework used by webhook retry tests.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["retry"],
                price=Decimal("149.00"),
                currency="USD",
                license_types=["single_user", "team", "organizational"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            framework_id = framework.id

    transaction_id = uuid4()
    webhook_context["event"] = payment_intent_event(
        "evt_retry_after_failure",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    # First delivery: transaction row does not exist yet -> dispatch fails.
    first = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    assert first.status_code == 500
    async with async_session_factory() as session:
        failed_event = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.provider_event_id == "evt_retry_after_failure"
            )
        )
    assert failed_event is not None
    assert failed_event.status == "failed"

    # The transaction the event referenced now exists (write race resolved).
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Transaction(
                    id=transaction_id,
                    payer_id=operator_id,
                    payee_id=contributor_id,
                    amount=Decimal("149.00"),
                    currency="USD",
                    platform_commission=Decimal("0.00"),
                    net_amount=Decimal("149.00"),
                    transaction_type="purchase",
                    status="pending",
                    provider="stripe",
                    provider_ref="pi_webhook_123",
                    ref_id=framework_id,
                    ref_type="framework",
                )
            )

    # Redelivery of the same event must now reprocess and grant the License.
    retry = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        completed = await session.get(Transaction, transaction_id)
        licenses = (
            (
                await session.execute(
                    select(License).where(License.framework_id == framework_id)
                )
            )
            .scalars()
            .all()
        )
        processed_event = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.provider_event_id == "evt_retry_after_failure"
            )
        )

    assert retry.status_code == 200
    assert retry.json() == {"received": True, "status": "processed"}
    assert completed is not None
    assert completed.status == "completed"
    assert len(licenses) == 1
    assert processed_event is not None
    assert processed_event.status == "processed"


async def test_stripe_payment_intent_success_funds_escrow_once(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified escrow webhook creates one held escrow ledger row."""
    (
        transaction_id,
        milestone_id,
        operator_id,
    ) = await create_pending_escrow_transaction()
    webhook_context["event"] = payment_intent_event(
        "evt_escrow_success",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=milestone_id,
        kind="escrow",
        provider_ref="pi_escrow_123",
        extra_metadata={
            "release_conditions": (
                '{"kind":"project_milestone","required_event":"operator_approval"}'
            )
        },
    )

    first = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    replay = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        escrows = (await session.execute(select(Escrow))).scalars().all()
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "escrow_funded")
        )

    assert first.status_code == 200
    assert first.json() == {"received": True, "status": "processed"}
    assert replay.status_code == 200
    assert replay.json() == {"received": True, "status": "duplicate"}
    assert transaction is not None
    assert transaction.status == "completed"
    assert len(escrows) == 1
    assert escrows[0].ref_id == milestone_id
    assert escrows[0].ref_type == "project_milestone"
    assert escrows[0].transaction_id == transaction_id
    assert escrows[0].status == "held"
    assert escrows[0].release_conditions["required_event"] == "operator_approval"
    assert audit is not None
    assert audit.actor_id == operator_id


async def test_stripe_attestation_fee_success_holds_escrow_and_starts_matching(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified Attestation fee webhook holds escrow and starts matching."""
    (
        transaction_id,
        attestation_id,
        operator_id,
    ) = await create_pending_attestation_fee_transaction()
    webhook_context["event"] = payment_intent_event(
        "evt_attestation_escrow_success",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=attestation_id,
        kind="escrow",
        provider_ref="pi_attestation_escrow_123",
        extra_metadata={
            "attestation_id": str(attestation_id),
            "release_conditions": (
                "{"
                '"kind":"attestation",'
                f'"attestation_id":"{attestation_id}",'
                f'"requestor_user_id":"{operator_id}"'
                "}"
            ),
        },
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        attestation = await session.get(Attestation, attestation_id)
        escrow = await session.scalar(select(Escrow))
        funded_audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "attestation_fee_funded")
        )
        needs_admin_audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "attestation_needs_admin")
        )

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "processed"}
    assert transaction is not None
    assert transaction.status == "completed"
    assert escrow is not None
    assert escrow.ref_id == attestation_id
    assert escrow.ref_type == "attestation"
    assert escrow.status == "held"
    assert attestation is not None
    assert attestation.status == "needs_admin"
    assert attestation.escrow_id == escrow.id
    assert funded_audit is not None
    assert funded_audit.actor_id == operator_id
    assert needs_admin_audit is not None


async def test_stripe_attestation_fee_failure_or_cancel_cancels_request(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """Failed or cancelled Attestation fee webhooks cancel the request."""
    (
        failed_transaction_id,
        failed_attestation_id,
        _,
    ) = await create_pending_attestation_fee_transaction(
        email="attestation-failed-operator@auracles.space",
        provider_ref="pi_attestation_failed_123",
    )
    webhook_context["event"] = payment_intent_event(
        "evt_attestation_escrow_failed",
        "payment_intent.payment_failed",
        transaction_id=failed_transaction_id,
        framework_id=failed_attestation_id,
        kind="escrow",
        provider_ref="pi_attestation_failed_123",
        extra_metadata={"attestation_id": str(failed_attestation_id)},
    )

    failed = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    (
        cancelled_transaction_id,
        cancelled_attestation_id,
        _,
    ) = await create_pending_attestation_fee_transaction(
        email="attestation-cancelled-operator@auracles.space",
        provider_ref="pi_attestation_cancelled_123",
    )
    webhook_context["event"] = payment_intent_event(
        "evt_attestation_escrow_cancelled",
        "payment_intent.canceled",
        transaction_id=cancelled_transaction_id,
        framework_id=cancelled_attestation_id,
        kind="escrow",
        provider_ref="pi_attestation_cancelled_123",
        extra_metadata={"attestation_id": str(cancelled_attestation_id)},
    )

    cancelled = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        failed_transaction = await session.get(Transaction, failed_transaction_id)
        failed_attestation = await session.get(Attestation, failed_attestation_id)
        cancelled_transaction = await session.get(
            Transaction,
            cancelled_transaction_id,
        )
        cancelled_attestation = await session.get(
            Attestation,
            cancelled_attestation_id,
        )
        audits = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "attestation_fee_failed")
                )
            )
            .scalars()
            .all()
        )
        purchase_failed_audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_failed")
        )

    assert failed.status_code == 200
    assert failed.json() == {"received": True, "status": "processed"}
    assert cancelled.status_code == 200
    assert cancelled.json() == {"received": True, "status": "processed"}
    assert failed_transaction is not None
    assert failed_transaction.status == "failed"
    assert failed_attestation is not None
    assert failed_attestation.status == "cancelled"
    assert cancelled_transaction is not None
    assert cancelled_transaction.status == "failed"
    assert cancelled_attestation is not None
    assert cancelled_attestation.status == "cancelled"
    assert len(audits) == 2
    assert purchase_failed_audit is None


async def test_stripe_escrow_webhook_marks_project_milestone_funded(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """Project Milestone escrow success moves the workspace into funded state."""
    (
        transaction_id,
        project_id,
        milestone_id,
        operator_id,
    ) = await create_pending_project_milestone_transaction()
    webhook_context["event"] = payment_intent_event(
        "evt_project_escrow_success",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=milestone_id,
        kind="escrow",
        provider_ref="pi_project_escrow_123",
        extra_metadata={
            "project_id": str(project_id),
            "milestone_id": str(milestone_id),
            "release_conditions": (
                "{"
                '"kind":"project_milestone",'
                f'"project_id":"{project_id}",'
                f'"milestone_id":"{milestone_id}",'
                f'"approver_user_id":"{operator_id}"'
                "}"
            ),
        },
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        project = await session.get(Project, project_id)
        milestone = await session.get(Milestone, milestone_id)
        escrow = await session.scalar(select(Escrow))
        message = await session.scalar(select(WorkspaceMessage))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "milestone_funded")
        )

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "processed"}
    assert transaction is not None
    assert transaction.status == "completed"
    assert escrow is not None
    assert project is not None
    assert project.status == "in_progress"
    assert milestone is not None
    assert milestone.status == "funded"
    assert milestone.funded_at is not None
    assert milestone.escrow_id == escrow.id
    assert message is not None
    assert message.system_event == "milestone_funded"
    assert audit is not None
    assert audit.actor_id == operator_id


async def test_milestone_funding_webhook_notifies_contributor(
    client: AsyncClient,
    webhook_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Funding a Project Milestone notifies the assigned Contributor.

    The Contributor only starts billable work once escrow is funded, so the
    funding webhook fans a milestone_funded notification to them.
    """
    from app.modules.projects import notifications as project_notifications

    calls: list[dict[str, Any]] = []

    class _Recorder:
        """Capture notification dispatches without using Celery or Redis."""

        def delay(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(
        project_notifications,
        "dispatch_project_notification",
        _Recorder(),
    )

    (
        transaction_id,
        project_id,
        milestone_id,
        operator_id,
    ) = await create_pending_project_milestone_transaction()
    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        assert transaction is not None
        contributor_id = transaction.payee_id

    webhook_context["event"] = payment_intent_event(
        "evt_project_escrow_notify",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=milestone_id,
        kind="escrow",
        provider_ref="pi_project_escrow_123",
        extra_metadata={
            "project_id": str(project_id),
            "milestone_id": str(milestone_id),
            "release_conditions": (
                "{"
                '"kind":"project_milestone",'
                f'"project_id":"{project_id}",'
                f'"milestone_id":"{milestone_id}",'
                f'"approver_user_id":"{operator_id}"'
                "}"
            ),
        },
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    assert response.status_code == 200
    funded_calls = [
        call for call in calls if call["notification_type"] == "milestone_funded"
    ]
    assert len(funded_calls) == 1
    assert funded_calls[0]["user_id"] == str(contributor_id)


async def test_stripe_webhook_rejects_bad_signature_before_event_storage(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """Invalid signatures return 400 and do not create webhook event rows."""
    webhook_context["event"] = {"id": "evt_bad", "type": "payment_intent.succeeded"}

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "bad-signature"},
    )

    async with async_session_factory() as session:
        event = await session.scalar(select(WebhookEvent))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "webhook_signature_invalid")
        )

    assert response.status_code == 400
    assert event is None
    assert audit is not None
    assert audit.metadata_["provider"] == "stripe"


async def test_stripe_payment_intent_failure_marks_purchase_failed(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified payment failure webhook marks the local purchase failed."""
    transaction_id, framework_id, _, _ = await create_pending_purchase()
    webhook_context["event"] = payment_intent_event(
        "evt_purchase_failed",
        "payment_intent.payment_failed",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.scalar(select(License))
        event = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.provider_event_id == "evt_purchase_failed"
            )
        )
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_failed")
        )

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "processed"}
    assert transaction is not None
    assert transaction.status == "failed"
    assert license_row is None
    assert event is not None
    assert event.status == "processed"
    assert audit is not None
    assert audit.target_id == transaction_id


async def create_processing_payout(*, provider_ref: str | None) -> tuple[UUID, UUID]:
    """Create a processing payout a transfer webhook can settle.

    Args:
        provider_ref: Stripe transfer id stored on the payout, or None to
            simulate a payout whose worker has not yet committed the reference.

    Returns:
        Tuple of (payout_id, contributor_id).
    """
    contributor_id = await create_user_with_roles(
        "payout-webhook-contributor@auracles.space",
        ["contributor"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            account = PayoutAccount(
                user_id=contributor_id,
                provider="stripe",
                provider_account_id="acct_webhook_payout",
                provider_account_lookup_hash="payout-webhook-lookup-hash",
                account_type="express",
            )
            session.add(account)
            await session.flush()
            payout = Payout(
                contributor_id=contributor_id,
                payout_account_id=account.id,
                amount=Decimal("100.00"),
                currency="USD",
                commission_deducted=Decimal("15.00"),
                net_amount=Decimal("85.00"),
                status="processing",
                provider_ref=provider_ref,
            )
            session.add(payout)
            await session.flush()
            return payout.id, contributor_id


def transfer_event(
    event_id: str,
    event_type: str,
    *,
    transfer_id: str,
    payout_id: UUID | None = None,
) -> dict[str, Any]:
    """Build a Stripe transfer webhook event payload."""
    metadata: dict[str, str] = {}
    if payout_id is not None:
        metadata["payout_id"] = str(payout_id)
    return {
        "id": event_id,
        "type": event_type,
        "data": {"object": {"id": transfer_id, "metadata": metadata}},
    }


async def test_stripe_transfer_created_completes_payout(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified transfer.created webhook marks the payout completed once.

    Stripe Connect transfers emit transfer.created, never transfer.paid, so the
    payout settlement path keys off the real event.
    """
    payout_id, contributor_id = await create_processing_payout(
        provider_ref="tr_webhook_payout_123"
    )
    webhook_context["event"] = transfer_event(
        "evt_transfer_created",
        "transfer.created",
        transfer_id="tr_webhook_payout_123",
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        payout = await session.get(Payout, payout_id)
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "payout_completed")
        )

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "processed"}
    assert payout is not None
    assert payout.status == "completed"
    assert payout.completed_at is not None
    assert audit is not None
    assert audit.target_id == payout_id
    assert audit.actor_id == contributor_id


async def test_stripe_transfer_reversed_fails_payout(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified transfer.reversed webhook marks the payout failed."""
    payout_id, _ = await create_processing_payout(provider_ref="tr_webhook_payout_456")
    webhook_context["event"] = transfer_event(
        "evt_transfer_reversed",
        "transfer.reversed",
        transfer_id="tr_webhook_payout_456",
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        payout = await session.get(Payout, payout_id)
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "payout_failed")
        )

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "processed"}
    assert payout is not None
    assert payout.status == "failed"
    assert payout.completed_at is None
    assert audit is not None
    assert audit.target_id == payout_id


async def test_stripe_transfer_reversed_notifies_admins(
    client: AsyncClient,
    webhook_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed payout fans out an admin-review alert after the status commits."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        webhook_service,
        "notify_admins_review_pending",
        lambda **kwargs: calls.append(kwargs),
    )
    payout_id, _ = await create_processing_payout(provider_ref="tr_notify_admins_789")
    webhook_context["event"] = transfer_event(
        "evt_transfer_reversed_notify",
        "transfer.reversed",
        transfer_id="tr_notify_admins_789",
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0]["domain"] == "payout"
    assert calls[0]["target_id"] == payout_id
    assert calls[0]["link"] == "/admin/payouts"


async def test_stripe_transfer_created_matches_by_metadata_when_ref_missing(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """transfer.created falls back to metadata payout_id and backfills the ref.

    Guards the race where the event arrives before the worker commits
    provider_ref onto the payout row.
    """
    payout_id, _ = await create_processing_payout(provider_ref=None)
    webhook_context["event"] = transfer_event(
        "evt_transfer_created_meta",
        "transfer.created",
        transfer_id="tr_webhook_payout_789",
        payout_id=payout_id,
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        payout = await session.get(Payout, payout_id)

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "processed"}
    assert payout is not None
    assert payout.status == "completed"
    assert payout.provider_ref == "tr_webhook_payout_789"


async def test_purchase_failure_records_ledger_event_with_cause(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A failed purchase records the transition and the bank's actual reason.

    Before the ledger, a failure stored only `status='failed'` plus an audit
    row whose reason was the constant event name, so every declined payment
    was indistinguishable from every other one.
    """
    transaction_id, framework_id, _, _ = await create_pending_purchase()
    event = payment_intent_event(
        "evt_purchase_failed_ledger",
        "payment_intent.payment_failed",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )
    event["data"]["object"]["last_payment_error"] = {
        "code": "card_declined",
        "decline_code": "insufficient_funds",
        "message": "Your card has insufficient funds.",
    }
    webhook_context["event"] = event

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        ledger_event = await session.scalar(
            select(FinancialEvent).where(FinancialEvent.entity_id == transaction_id)
        )

    assert response.status_code == 200
    assert ledger_event is not None
    assert ledger_event.entity_type == "transaction"
    assert ledger_event.event_type == "purchase_failed"
    assert ledger_event.from_status == "pending"
    assert ledger_event.to_status == "failed"
    assert ledger_event.reason_code == "insufficient_funds"
    assert ledger_event.reason_message == "Your card has insufficient funds."
    assert ledger_event.provider == "stripe"


async def test_payout_reversal_records_ledger_transition(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A reversed payout transfer is traceable, with its full transfer reference.

    `transfer.reversed` is the failure path Stripe actually emits for Connect
    transfers, and it carries no failure code. The reason is therefore
    `unknown` — honest rather than invented — while the ledger still records
    the transition and the whole transfer reference. The existing audit row
    keeps only the reference's last four characters, which is not enough to
    reconcile against the Stripe dashboard.
    """
    payout_id, _ = await create_processing_payout(provider_ref="tr_failed_payout_1")
    webhook_context["event"] = transfer_event(
        "evt_transfer_reversed_ledger",
        "transfer.reversed",
        transfer_id="tr_failed_payout_1",
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        ledger_event = await session.scalar(
            select(FinancialEvent).where(FinancialEvent.entity_id == payout_id)
        )

    assert response.status_code == 200
    assert ledger_event is not None
    assert ledger_event.entity_type == "payout"
    assert ledger_event.event_type == "payout_failed"
    assert ledger_event.from_status == "processing"
    assert ledger_event.to_status == "failed"
    assert ledger_event.reason_code == "unknown"
    assert ledger_event.provider_ref == "tr_failed_payout_1"


async def test_successful_purchase_records_ledger_transition(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """Successful money movement is traceable too, not only failures.

    A ledger that holds only failures cannot answer how long a payment took or
    prove that a completed purchase ever settled.
    """
    transaction_id, framework_id, _, _ = await create_pending_purchase()
    webhook_context["event"] = payment_intent_event(
        "evt_purchase_succeeded_ledger",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        ledger_event = await session.scalar(
            select(FinancialEvent).where(
                FinancialEvent.entity_id == transaction_id,
                FinancialEvent.event_type == "purchase_completed",
            )
        )

    assert response.status_code == 200
    assert ledger_event is not None
    assert ledger_event.from_status == "pending"
    assert ledger_event.to_status == "completed"
    assert ledger_event.reason_code is None
    assert ledger_event.amount is not None
