"""Money-path notice fixes approved by the human on 2026-09-14.

Two gaps surfaced during the organizations end-to-end rework:

- A Paystack purchase with partner attribution created the partner webhook
  delivery rows but never dispatched them: the Paystack branch discarded the
  post-commit partner work the shared purchase settlement returns. Stripe
  purchases always dispatched them.
- A Stripe ``payout.failed`` (the connected account's own bank payout) only
  alerted admins. The contributor or organization whose money was stranded in
  their Stripe balance was never told. No payout row changes status: the funds
  sit in the connected balance, not ours, so re-crediting would pay twice.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory
from app.core.security import hash_payout_provider_account_id
from app.modules.developer import webhooks_service as developer_webhooks_service
from app.modules.developer.models import ApiKey, PartnerWebhook, PartnerWebhookDelivery
from app.modules.financials import notifications as financial_notifications
from app.modules.financials.models import PayoutAccount
from app.modules.organizations import notifications as org_notifications
from app.modules.organizations.models import Organization, OrgMember
from tests.integration.test_paystack_webhooks import (  # noqa: F401 - fixture
    charge_event,
    create_pending_paystack_purchase,
    paystack_context,
    post_webhook,
)
from tests.integration.test_stripe_webhooks import (  # noqa: F401 - fixture
    create_connected_payout_account,
    create_partner_attribution,
    create_user_with_roles,
    webhook_context,
)

pytestmark = pytest.mark.asyncio


class _RecordingDispatch:
    """Capture queued notifications instead of hitting Celery."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def delay(self, **kwargs: Any) -> None:
        """Record one dispatch call."""
        self.sent.append(kwargs)

    def of_type(self, notification_type: str) -> list[dict[str, Any]]:
        """Return the calls for one notification type."""
        return [c for c in self.sent if c["notification_type"] == notification_type]


class _RecordingDeliveryTask:
    """Capture partner webhook delivery dispatches."""

    def __init__(self) -> None:
        self.queued: list[str] = []

    def delay(self, delivery_id: str) -> None:
        """Record one queued delivery id."""
        self.queued.append(delivery_id)


def _bank_payout_failed_event(account_id: str, payout_ref: str) -> dict[str, Any]:
    """Build a verified Stripe ``payout.failed`` for a connected account."""
    return {
        "id": f"evt_{payout_ref}",
        "type": "payout.failed",
        "account": account_id,
        "data": {
            "object": {
                "id": payout_ref,
                "failure_code": "account_closed",
                "failure_message": "The bank account has been closed.",
            }
        },
    }


async def _post_stripe(client: AsyncClient) -> Any:
    """POST the configured Stripe event with a valid signature."""
    return await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )


async def test_paystack_purchase_dispatches_partner_webhook_deliveries(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811 - imported fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partner-attributed Paystack purchase queues its partner webhook delivery.

    Mirrors Stripe: the delivery row is created in the settlement transaction
    and dispatched once that transaction commits.
    """
    task = _RecordingDeliveryTask()
    monkeypatch.setattr(developer_webhooks_service, "deliver_partner_webhook", task)
    transaction_id, framework_id, operator_id = await create_pending_paystack_purchase()
    api_key_id = await create_partner_attribution(
        transaction_id=transaction_id,
        framework_id=framework_id,
        buyer_user_id=operator_id,
    )
    async with async_session_factory() as session:
        async with session.begin():
            account_id = await session.scalar(
                select(ApiKey.developer_account_id).where(ApiKey.id == api_key_id)
            )
            session.add(
                PartnerWebhook(
                    developer_account_id=account_id,
                    url="https://partner.example.com/hooks",
                    secret_encrypted="encrypted-test-secret",
                    events=["purchase.confirmed"],
                    active=True,
                )
            )
    paystack_context["event"] = charge_event(
        "charge.success",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    try:
        response = await post_webhook(client)
        async with async_session_factory() as session:
            delivery_ids = list(
                (await session.execute(select(PartnerWebhookDelivery.id))).scalars()
            )

        assert response.status_code == 200
        assert response.json() == {"received": True, "status": "processed"}
        assert len(delivery_ids) == 1
        assert task.queued == [str(delivery_ids[0])]
    finally:
        # The shared webhook reset clears developer accounts but not their
        # webhooks, which would otherwise block that delete.
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(PartnerWebhookDelivery))
                await session.execute(delete(PartnerWebhook))


async def test_bank_payout_failure_tells_the_contributor(
    client: AsyncClient,
    webhook_context: dict[str, Any],  # noqa: F811 - imported fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contributor learns why the bank payout failed and that funds are safe."""
    recorder = _RecordingDispatch()
    monkeypatch.setattr(
        financial_notifications, "dispatch_project_notification", recorder
    )
    contributor_id = await create_connected_payout_account("acct_contrib_bank_fail")
    webhook_context["event"] = _bank_payout_failed_event(
        "acct_contrib_bank_fail", "po_contrib_1"
    )

    response = await _post_stripe(client)

    assert response.status_code == 200
    sent = recorder.of_type("payout_failed")
    assert [call["user_id"] for call in sent] == [str(contributor_id)]
    assert "The bank account has been closed." in sent[0]["body"]
    assert "Stripe balance" in sent[0]["body"]
    assert sent[0]["link"] == "/dashboard/financials"


async def test_bank_payout_failure_tells_org_owners(
    client: AsyncClient,
    webhook_context: dict[str, Any],  # noqa: F811 - imported fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An org's failed bank payout reaches its owners with a link to financials."""
    recorder = _RecordingDispatch()
    monkeypatch.setattr(org_notifications, "dispatch_project_notification", recorder)
    owner_id = await create_user_with_roles(
        "bank-payout-org-owner@auracles.space", ["contributor"]
    )
    org_id: UUID
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                slug=f"bank-payout-{uuid4().hex[:8]}",
                name="Lagos Audit Partners",
                country="NG",
                created_by=owner_id,
            )
            session.add(organization)
            await session.flush()
            org_id = organization.id
            session.add(OrgMember(org_id=org_id, user_id=owner_id, role="owner"))
            session.add(
                PayoutAccount(
                    org_id=org_id,
                    provider="stripe",
                    provider_account_id="acct_org_bank_fail",
                    provider_account_lookup_hash=hash_payout_provider_account_id(
                        "acct_org_bank_fail"
                    ),
                    account_type="express",
                )
            )
    webhook_context["event"] = _bank_payout_failed_event(
        "acct_org_bank_fail", "po_org_1"
    )

    try:
        response = await _post_stripe(client)

        assert response.status_code == 200
        sent = recorder.of_type("org_payout_failed")
        assert [call["user_id"] for call in sent] == [str(owner_id)]
        assert "The bank account has been closed." in sent[0]["body"]
        assert sent[0]["link"] == f"/dashboard/organizations/{org_id}/financials"
    finally:
        # Organizations are outside the shared webhook reset; remove them so
        # the identity cleanup can delete the owner.
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    delete(PayoutAccount).where(PayoutAccount.org_id == org_id)
                )
                await session.execute(
                    delete(OrgMember).where(OrgMember.org_id == org_id)
                )
                await session.execute(
                    delete(Organization).where(Organization.id == org_id)
                )
