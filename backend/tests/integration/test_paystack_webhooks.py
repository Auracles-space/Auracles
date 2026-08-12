"""Integration tests for Paystack webhook ingestion and dispatch.

Paystack's envelope differs from Stripe's in three ways that matter here: the
event name is `event` not `type`, the object sits directly under `data` rather
than `data.object`, and there is no provider event id at all. These tests pin
the behaviour that falls out of those differences — most importantly that
idempotency still holds without an event id to key on.

Maps to: FR-FIN-* (Nigerian corridor checkout).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory, engine
from app.core.security import (
    encrypt_payout_provider_account_id,
    hash_payout_provider_account_id,
)
from app.integrations.paystack import PaystackProviderError
from app.modules.auth.models import User, UserRole
from app.modules.developer.models import (
    ApiKey,
    DeveloperAccount,
    DeveloperApplication,
    PartnerCommission,
)
from app.modules.financials.models import (
    FinancialEvent,
    Payout,
    PayoutAccount,
    Transaction,
)
from app.modules.frameworks.models import Framework, License
from app.modules.webhooks import service as webhook_service
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog
from tests.integration.test_stripe_webhooks import (
    FakeInvoiceTask,
    reset_webhook_state,
)

PAYSTACK_REFERENCE = "auracles_ref_ngn_001"


@pytest.fixture
async def paystack_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state and install a controllable Paystack verifier double."""
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
            raise PaystackProviderError("bad signature")
        event = context["event"]
        if not isinstance(event, dict):
            raise PaystackProviderError("missing test event")
        return event

    monkeypatch.setattr(
        webhook_service.paystack,
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


async def create_pending_paystack_purchase() -> tuple[UUID, UUID, UUID]:
    """Create a pending Paystack purchase a webhook can settle."""
    contributor_id = await create_user_with_roles(
        "paystack-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "paystack-operator@auracles.space",
        ["operator"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Paystack Purchase Framework",
                description="Framework used by Paystack webhook tests.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["paystack", "webhook"],
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
                provider="paystack",
                provider_ref=PAYSTACK_REFERENCE,
                ref_id=framework.id,
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id, framework.id, operator_id


def charge_event(
    event_name: str,
    *,
    transaction_id: UUID,
    framework_id: UUID,
    reference: str = PAYSTACK_REFERENCE,
    gateway_response: str | None = None,
    license_type: str = "team",
) -> dict[str, Any]:
    """Build a Paystack charge event in the provider's own envelope shape."""
    data: dict[str, Any] = {
        "id": 302961,
        "reference": reference,
        "amount": 14900,
        "currency": "USD",
        "status": "success" if event_name == "charge.success" else "failed",
        "metadata": {
            "transaction_id": str(transaction_id),
            "kind": "purchase",
            "framework_id": str(framework_id),
            "license_type": license_type,
        },
    }
    if gateway_response is not None:
        data["gateway_response"] = gateway_response
    return {"event": event_name, "data": data}


async def post_webhook(
    client: AsyncClient,
    *,
    signature: str = "valid-signature",
) -> Any:
    """POST a Paystack webhook with the given signature header."""
    return await client.post(
        "/v1/webhooks/paystack",
        content=b'{"raw":true}',
        headers={"x-paystack-signature": signature},
    )


async def test_charge_success_completes_purchase_and_grants_license(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """A verified charge.success completes the purchase and grants access."""
    transaction_id, framework_id, operator_id = (
        await create_pending_paystack_purchase()
    )
    paystack_context["event"] = charge_event(
        "charge.success",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    response = await post_webhook(client)

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

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "processed"}
    assert transaction is not None
    assert transaction.status == "completed"
    assert len(licenses) == 1
    assert licenses[0].operator_id == operator_id
    assert licenses[0].license_type == "team"


async def test_charge_success_replay_is_a_duplicate(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """Redelivery is idempotent even though Paystack sends no event id.

    The stored event id is derived from the event name and charge reference,
    so a second delivery of the same charge must not mint a second License.
    """
    transaction_id, framework_id, _ = await create_pending_paystack_purchase()
    paystack_context["event"] = charge_event(
        "charge.success",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    first = await post_webhook(client)
    replay = await post_webhook(client)

    async with async_session_factory() as session:
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

    assert first.json() == {"received": True, "status": "processed"}
    assert replay.json() == {"received": True, "status": "duplicate"}
    assert len(licenses) == 1
    assert len(events) == 1
    assert events[0].provider == "paystack"


async def test_charge_failed_records_normalized_cause_from_prose(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """A failed charge stores Paystack's prose as a canonical reason code.

    Paystack publishes no stable failure codes, so the ledger's value comes
    from matching `gateway_response` prose — the whole reason the normalizer
    exists.
    """
    transaction_id, framework_id, _ = await create_pending_paystack_purchase()
    paystack_context["event"] = charge_event(
        "charge.failed",
        transaction_id=transaction_id,
        framework_id=framework_id,
        gateway_response="Insufficient Funds",
    )

    response = await post_webhook(client)

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        ledger = await session.scalar(
            select(FinancialEvent).where(
                FinancialEvent.entity_id == transaction_id,
                FinancialEvent.event_type == "purchase_failed",
            )
        )

    assert response.status_code == 200
    assert transaction is not None
    assert transaction.status == "failed"
    assert ledger is not None
    assert ledger.provider == "paystack"
    assert ledger.reason_code == "insufficient_funds"


async def test_invalid_signature_is_rejected_and_audited(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """An unverified payload is refused with 400 and never dispatched."""
    transaction_id, framework_id, _ = await create_pending_paystack_purchase()
    paystack_context["event"] = charge_event(
        "charge.success",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    response = await post_webhook(client, signature="bad-signature")

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        events = (await session.execute(select(WebhookEvent))).scalars().all()
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "webhook_signature_invalid")
        )

    assert response.status_code == 400
    assert transaction is not None
    assert transaction.status == "pending"
    assert events == []
    assert audit is not None
    assert audit.metadata_["provider"] == "paystack"


async def test_charge_for_a_stripe_transaction_is_refused(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """A Paystack event must never settle a transaction booked to Stripe.

    Metadata is attacker-influencable in principle, so the provider stamped on
    the transaction is the authority on which rail may complete it.
    """
    transaction_id, framework_id, _ = await create_pending_paystack_purchase()
    async with async_session_factory() as session:
        async with session.begin():
            transaction = await session.get(Transaction, transaction_id)
            assert transaction is not None
            transaction.provider = "stripe"
    paystack_context["event"] = charge_event(
        "charge.success",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    response = await post_webhook(client)

    async with async_session_factory() as session:
        settled = await session.get(Transaction, transaction_id)
        licenses = (
            (
                await session.execute(
                    select(License).where(License.framework_id == framework_id)
                )
            )
            .scalars()
            .all()
        )
        event_row = await session.scalar(select(WebhookEvent))

    assert response.status_code == 500
    assert settled is not None
    assert settled.status == "pending"
    assert licenses == []
    assert event_row is not None
    assert event_row.status == "failed"
    assert event_row.error is not None


async def test_reference_mismatch_is_refused(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """A charge whose reference is not the one we initiated must not settle."""
    transaction_id, framework_id, _ = await create_pending_paystack_purchase()
    paystack_context["event"] = charge_event(
        "charge.success",
        transaction_id=transaction_id,
        framework_id=framework_id,
        reference="someone_elses_reference",
    )

    response = await post_webhook(client)

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)

    assert response.status_code == 500
    assert transaction is not None
    assert transaction.status == "pending"


async def test_unknown_event_type_is_stored_without_dispatch(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """Paystack sends events we do not handle; they must not error.

    Erroring would make Paystack retry an event we will never act on.
    """
    paystack_context["event"] = {
        "event": "subscription.create",
        "data": {"reference": f"sub_{uuid4().hex}"},
    }

    response = await post_webhook(client)

    async with async_session_factory() as session:
        event_row = await session.scalar(select(WebhookEvent))

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "received"}
    assert event_row is not None
    assert event_row.event_type == "subscription.create"


async def create_processing_paystack_payout() -> tuple[UUID, str]:
    """Create an in-flight Paystack payout a transfer event can settle."""
    contributor_id = await create_user_with_roles(
        f"paystack-payee-{uuid4()}@auracles.space",
        ["contributor"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            payout_account = PayoutAccount(
                user_id=contributor_id,
                provider="paystack",
                provider_account_id=encrypt_payout_provider_account_id(
                    "RCP_settle_1"
                ),
                provider_account_lookup_hash=hash_payout_provider_account_id(
                    "RCP_settle_1"
                ),
                account_type="nuban",
                is_default=True,
                verified_at=datetime.now(UTC),
            )
            session.add(payout_account)
            await session.flush()
            payout = Payout(
                contributor_id=contributor_id,
                payout_account_id=payout_account.id,
                amount=Decimal("100.00"),
                currency="USD",
                commission_deducted=Decimal("15.00"),
                net_amount=Decimal("85.00"),
                status="processing",
            )
            session.add(payout)
            await session.flush()
            payout.provider_ref = f"payout-{payout.id}"
            return payout.id, payout.provider_ref


def transfer_event(event_name: str, *, reference: str, reason: str = "") -> dict:
    """Build a Paystack transfer event in the provider's envelope shape."""
    data: dict[str, Any] = {
        "id": 998877,
        "reference": reference,
        "amount": 8500,
        "currency": "USD",
        "transfer_code": "TRF_settle_1",
        "status": "success" if event_name == "transfer.success" else "failed",
    }
    if reason:
        data["reason"] = reason
    return {"event": event_name, "data": data}


async def test_transfer_success_completes_the_payout(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """A successful transfer is the moment a Contributor's bank was funded.

    Unlike Stripe — where `transfer.created` only moves money into a connected
    account's balance — a Paystack transfer goes straight to the bank, so this
    event is genuinely terminal and completes the payout.
    """
    payout_id, reference = await create_processing_paystack_payout()
    paystack_context["event"] = transfer_event(
        "transfer.success",
        reference=reference,
    )

    response = await post_webhook(client)

    async with async_session_factory() as session:
        payout = await session.get(Payout, payout_id)
        assert payout is not None
        await session.refresh(payout)
        status_ = payout.status
        completed_at = payout.completed_at
        ledger = await session.scalar(
            select(FinancialEvent).where(
                FinancialEvent.entity_id == payout_id,
                FinancialEvent.event_type == "payout_completed",
            )
        )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert status_ == "completed"
    assert completed_at is not None
    assert ledger is not None
    assert ledger.provider == "paystack"


async def test_transfer_failed_records_the_cause_and_alerts_admins(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """A failed transfer must leave the reason on the payout's ledger trail.

    Paystack states the cause in prose, so it goes through the Paystack
    normalizer — reading it with Stripe's coded parser would yield "unknown"
    and strand an admin with no reason to act on.
    """
    payout_id, reference = await create_processing_paystack_payout()
    paystack_context["event"] = transfer_event(
        "transfer.failed",
        reference=reference,
        reason="Account name mismatch",
    )

    response = await post_webhook(client)

    async with async_session_factory() as session:
        payout = await session.get(Payout, payout_id)
        assert payout is not None
        await session.refresh(payout)
        status_ = payout.status
        ledger = await session.scalar(
            select(FinancialEvent).where(
                FinancialEvent.entity_id == payout_id,
                FinancialEvent.event_type == "payout_failed",
            )
        )

    assert response.status_code == 200
    assert status_ == "failed"
    assert ledger is not None
    assert ledger.provider == "paystack"
    assert ledger.reason_message is not None


async def test_transfer_event_for_an_unknown_reference_is_acknowledged(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """A transfer we did not book must not error, or Paystack retries forever."""
    paystack_context["event"] = transfer_event(
        "transfer.success",
        reference="payout-00000000-0000-4000-8000-000000000000",
    )

    response = await post_webhook(client)

    assert response.status_code == 200


async def test_transfer_success_replay_does_not_recomplete_the_payout(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """Redelivery must not write a second completion to the ledger."""
    payout_id, reference = await create_processing_paystack_payout()
    paystack_context["event"] = transfer_event(
        "transfer.success",
        reference=reference,
    )

    first = await post_webhook(client)
    second = await post_webhook(client)

    async with async_session_factory() as session:
        ledger_rows = (
            (
                await session.execute(
                    select(FinancialEvent).where(
                        FinancialEvent.entity_id == payout_id,
                        FinancialEvent.event_type == "payout_completed",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert first.json()["status"] == "processed"
    assert second.json()["status"] == "duplicate"
    assert len(ledger_rows) == 1


async def create_refunded_paystack_purchase() -> tuple[UUID, UUID]:
    """Create a refunded Paystack purchase with the revoked licence it minted.

    Mirrors the state `refund_framework_purchase` leaves behind: because
    Paystack settles refunds asynchronously, the purchase is already marked
    refunded and access already revoked while the money is still in flight.
    """
    contributor_id = await create_user_with_roles(
        f"paystack-refund-contributor-{uuid4()}@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        f"paystack-refund-operator-{uuid4()}@auracles.space",
        ["operator"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Paystack Refund Framework",
                description="Framework used by Paystack refund webhook tests.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["paystack", "refund"],
                price=Decimal("149.00"),
                currency="USD",
                license_types=["single_user", "team"],
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
                status="refunded",
                provider="paystack",
                provider_ref=PAYSTACK_REFERENCE,
                ref_id=framework.id,
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            license_row = License(
                framework_id=framework.id,
                operator_id=operator_id,
                transaction_id=transaction.id,
                license_type="team",
                status="revoked",
                version_at_grant=framework.version,
                seats_used=1,
                seats_total=10,
            )
            session.add(license_row)
            await session.flush()
            return transaction.id, license_row.id


async def create_voided_partner_commission(transaction_id: UUID) -> UUID:
    """Void a Partner commission against a purchase, as the clearing task does.

    The commission is not voided by the refund itself — `clear_partner_commissions`
    voids it on its next run after seeing the purchase marked refunded. This
    reproduces the state where that run landed inside Paystack's settlement
    window, which is the only way a declined refund can find a voided commission.
    """
    developer_id = await create_user_with_roles(
        f"paystack-refund-developer-{uuid4()}@auracles.space",
        ["developer"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            transaction = await session.get(Transaction, transaction_id)
            assert transaction is not None
            application = DeveloperApplication(
                user_id=developer_id,
                company_name="Paystack Refund Partner",
                website="https://paystack-refund-partner.example.com",
                use_case="Verify commission reinstatement on a declined refund.",
                status="approved",
                reviewed_at=datetime.now(UTC),
            )
            session.add(application)
            await session.flush()
            account = DeveloperAccount(
                user_id=developer_id,
                application_id=application.id,
                company_name=application.company_name,
                commission_tier=1,
                tier_rate=Decimal("0.0500"),
            )
            session.add(account)
            await session.flush()
            api_key = ApiKey(
                developer_account_id=account.id,
                name="Paystack refund key",
                key_prefix="ak_psrf",
                key_hash=f"paystack-refund-hash-{uuid4()}",
                scopes=["purchase:write"],
            )
            session.add(api_key)
            await session.flush()
            commission = PartnerCommission(
                api_key_id=api_key.id,
                developer_account_id=account.id,
                transaction_id=transaction.id,
                framework_id=transaction.ref_id,
                sale_amount=Decimal("149.00"),
                currency="USD",
                tier_at_sale=1,
                tier_rate=Decimal("0.0500"),
                commission_amount=Decimal("7.45"),
                status="voided",
            )
            session.add(commission)
            await session.flush()
            return commission.id


def refund_event(
    event_name: str,
    *,
    reference: str = PAYSTACK_REFERENCE,
) -> dict[str, Any]:
    """Build a Paystack refund event in the provider's own envelope shape.

    Refund events name the charge under `transaction_reference`, not
    `reference` as charge events do.
    """
    return {
        "event": event_name,
        "data": {
            "status": "processed" if event_name == "refund.processed" else "failed",
            "transaction_reference": reference,
            "refund_reference": "rf_ref_001",
            "amount": 14900,
            "currency": "NGN",
        },
    }


async def test_refund_processed_confirms_the_refunded_purchase(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """Settlement confirmation leaves the already-refunded purchase as it is."""
    transaction_id, license_id = await create_refunded_paystack_purchase()
    paystack_context["event"] = refund_event("refund.processed")

    response = await post_webhook(client)

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.get(License, license_id)
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "refund_settled")
        )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert transaction is not None
    assert transaction.status == "refunded"
    assert license_row is not None
    assert license_row.status == "revoked"
    assert audit is not None
    assert audit.target_id == transaction_id


async def test_refund_failed_restores_the_purchase_and_access(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """A declined refund must give the buyer back what they paid for.

    Access was revoked optimistically when the refund was accepted. If the
    money never moves, the buyer has paid and holds nothing, so both the
    purchase and every licence it minted are restored.
    """
    transaction_id, license_id = await create_refunded_paystack_purchase()
    paystack_context["event"] = refund_event("refund.failed")

    response = await post_webhook(client)

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.get(License, license_id)
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "refund_failed")
        )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert transaction is not None
    assert transaction.status == "completed"
    assert license_row is not None
    assert license_row.status == "active"
    assert audit is not None
    assert audit.target_id == transaction_id


async def test_refund_failed_reinstates_a_voided_partner_commission(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """A commission voided by a refund that never happened must come back.

    The commission follows the sale. If Paystack declines the refund the sale
    stands, so the Partner is owed for it exactly as before; leaving it voided
    would keep their earnings for a purchase that was never reversed.

    It returns to `pending`, not `cleared` — clearing is the periodic task's
    decision to make against the 48-hour window, and this restores the row to
    the state that task expects to find.
    """
    transaction_id, _ = await create_refunded_paystack_purchase()
    commission_id = await create_voided_partner_commission(transaction_id)
    paystack_context["event"] = refund_event("refund.failed")

    response = await post_webhook(client)

    async with async_session_factory() as session:
        commission = await session.get(PartnerCommission, commission_id)
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "partner_commission_reinstated")
        )

    assert response.status_code == 200
    assert commission is not None
    assert commission.status == "pending"
    assert commission.cleared_at is None
    assert audit is not None
    assert audit.target_id == commission_id
    assert audit.metadata_["transaction_id"] == str(transaction_id)


async def test_refund_event_for_an_unknown_reference_is_acknowledged(
    client: AsyncClient,
    paystack_context: dict[str, Any],
) -> None:
    """A refund we did not book must not error, or Paystack retries forever."""
    paystack_context["event"] = refund_event(
        "refund.processed",
        reference="auracles_ref_never_seen",
    )

    response = await post_webhook(client)

    assert response.status_code == 200
