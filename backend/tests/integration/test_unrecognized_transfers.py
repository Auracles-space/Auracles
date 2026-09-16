"""Integration tests for detecting Paystack transfers Auracles did not start.

Anyone with Paystack dashboard access can move money out of the balance that
holds users' funds. Such a transfer used to be acknowledged and silently
ignored. It must now be recorded, raise an instant alert to every admin, show
on Treasury until the super-admin marks it reviewed, and alert only once per
transfer however many events Paystack sends for it.

Maps to: platform treasury design, decision 5.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.modules.auth.models import User, UserRole
from app.modules.financials import treasury, unrecognized_transfers
from app.modules.financials.models import Payout, UnrecognizedTransfer
from app.shared.models.audit_log import AuditLog
from tests.integration.test_paystack_webhooks import (  # noqa: F401
    create_processing_paystack_payout,
    paystack_context,
    post_webhook,
    transfer_event,
)

LIST_PATH = "/v1/admin/treasury/unrecognized-transfers"


def _rogue_event(event_name: str = "transfer.success", reference: str = "") -> dict:
    """Build a transfer event for a transfer made from the Paystack dashboard."""
    event = transfer_event(event_name, reference=reference or f"dash-{uuid4().hex}")
    event["data"].update(
        {
            "amount": 50_000_000,
            "currency": "NGN",
            "recipient": {
                "name": "Chidi Okafor",
                "details": {"account_number": "0987654321", "bank_name": "Kuda Bank"},
            },
        }
    )
    return event


def _capture(monkeypatch: Any) -> list[dict[str, Any]]:
    """Record admin notifications instead of queueing them."""
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        unrecognized_transfers,
        "notify_admins_review_pending",
        lambda **kwargs: captured.append(kwargs),
    )
    return captured


async def _admin(*, superadmin: bool) -> UUID:
    """Create an admin, optionally the super-admin."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"rogue-admin-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name="Rogue Watch",
                email_verified=True,
                is_superadmin=superadmin,
            )
            session.add(user)
            await session.flush()
            session.add(UserRole(user_id=user.id, role="admin"))
        return user.id


def _headers(user_id: UUID) -> dict[str, str]:
    """Build admin bearer headers."""
    token = create_access_token(user_id=user_id, roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


async def _rows() -> list[UnrecognizedTransfer]:
    """Return every recorded unrecognized transfer."""
    async with async_session_factory() as session:
        return list((await session.execute(select(UnrecognizedTransfer))).scalars())


async def test_a_dashboard_transfer_is_recorded_and_alerts_admins(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
    monkeypatch: Any,
) -> None:
    """A transfer matching no payout or withdrawal is recorded with safe details."""
    notifications = _capture(monkeypatch)
    event = _rogue_event()
    paystack_context["event"] = event

    response = await post_webhook(client)

    assert response.json()["status"] == "processed"
    rows = await _rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.provider == "paystack"
    assert row.provider_ref == event["data"]["reference"]
    assert row.event_type == "transfer.success"
    assert str(row.amount) == "500000.00"
    assert row.currency == "NGN"
    assert row.recipient_name == "Chidi Okafor"
    assert row.recipient_bank == "Kuda Bank"
    assert row.recipient_last4 == "4321"
    assert row.acknowledged_at is None
    assert [n["domain"] for n in notifications] == ["unrecognized_transfer"]
    assert "500000.00" in notifications[0]["body"]
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "unrecognized_transfer_detected")
        )
    assert audit is not None


async def test_later_events_for_the_same_transfer_alert_once(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
    monkeypatch: Any,
) -> None:
    """A success then a reversal is one transfer, one row, one alert."""
    notifications = _capture(monkeypatch)
    reference = f"dash-{uuid4().hex}"
    paystack_context["event"] = _rogue_event("transfer.success", reference)
    await post_webhook(client)
    paystack_context["event"] = _rogue_event("transfer.reversed", reference)

    await post_webhook(client)

    rows = await _rows()
    assert len(rows) == 1
    assert rows[0].event_type == "transfer.reversed"
    assert len(notifications) == 1


async def test_a_known_payout_transfer_is_not_flagged(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
    monkeypatch: Any,
) -> None:
    """Transfers Auracles started still settle their payout as before."""
    notifications = _capture(monkeypatch)
    payout_id, reference = await create_processing_paystack_payout()
    paystack_context["event"] = transfer_event("transfer.success", reference=reference)

    await post_webhook(client)

    assert await _rows() == []
    assert notifications == []
    async with async_session_factory() as session:
        payout = await session.get(Payout, payout_id)
    assert payout is not None
    assert payout.status == "completed"


async def test_admins_list_and_the_superadmin_acknowledges(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
    monkeypatch: Any,
) -> None:
    """Any admin sees the list; only the super-admin marks one reviewed."""
    _capture(monkeypatch)
    paystack_context["event"] = _rogue_event()
    await post_webhook(client)
    admin_id = await _admin(superadmin=False)
    superadmin_id = await _admin(superadmin=True)

    listed = await client.get(LIST_PATH, headers=_headers(admin_id))
    transfer_id = listed.json()["transfers"][0]["id"]
    ack_path = f"{LIST_PATH}/{transfer_id}/acknowledge"
    by_admin = await client.post(ack_path, headers=_headers(admin_id))
    by_superadmin = await client.post(ack_path, headers=_headers(superadmin_id))

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["transfers"][0]["recipient_last4"] == "4321"
    assert by_admin.status_code == 403
    assert by_superadmin.status_code == 200
    assert by_superadmin.json()["acknowledged_by"] == str(superadmin_id)
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "unrecognized_transfer_acknowledged"
            )
        )
    assert audit is not None
    assert audit.actor_id == superadmin_id


async def test_treasury_counts_transfers_awaiting_review(
    paystack_context: dict[str, Any],  # noqa: F811
    client: AsyncClient,
    monkeypatch: Any,
) -> None:
    """The summary carries how many unrecognized transfers are unreviewed."""
    _capture(monkeypatch)

    async def fake_fetch_balance(**_: Any) -> dict[str, int]:
        """Return an empty balance."""
        return {"NGN": 0}

    monkeypatch.setattr(treasury.paystack, "fetch_balance", fake_fetch_balance)
    paystack_context["event"] = _rogue_event()
    await post_webhook(client)
    admin_id = await _admin(superadmin=False)

    summary = await client.get("/v1/admin/treasury/summary", headers=_headers(admin_id))

    assert summary.json()["unreviewed_unrecognized_transfers"] == 1
