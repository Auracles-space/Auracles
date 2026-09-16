"""Integration tests for the admin Treasury summary.

The summary answers how much of the money in the Paystack balance belongs to
users, how much is the platform's, and how much of the platform's share can be
withdrawn now. Getting "owed to users" wrong would let the platform withdraw
users' money, so each line is pinned against a seeded ledger and cross-checked
against the per-account balance the payout flow itself enforces.

Maps to: FR-FIN-* / FR-ADMIN-* (platform treasury, spec §Definitions).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token
from app.integrations.paystack import PaystackProviderError
from app.modules.auth.models import User, UserRole
from app.modules.developer.models import (
    ApiKey,
    DeveloperAccount,
    DeveloperApplication,
    PartnerCommission,
)
from app.modules.financials import service as financials_service
from app.modules.financials import treasury
from app.modules.financials.models import (
    Escrow,
    Payout,
    PayoutAccount,
    ProviderFee,
    Transaction,
)
from app.modules.frameworks.models import Framework
from app.modules.organizations.models import Organization
from tests.support.db_cleanup import clear_identity_state_async

SUMMARY_PATH = "/v1/admin/treasury/summary"


async def _reset() -> None:
    """Remove treasury test data in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(ProviderFee))
        await session.execute(delete(PartnerCommission))
        await session.execute(delete(ApiKey))
        await session.execute(delete(DeveloperAccount))
        await session.execute(delete(DeveloperApplication))
        await session.execute(delete(Payout))
        await session.execute(delete(PayoutAccount))
        await session.execute(delete(Escrow))
        await session.execute(delete(Transaction))
        await session.execute(delete(Framework))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
async def treasury_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state and install a controllable Paystack balance double."""
    await engine.dispose()
    await _reset()
    context: dict[str, Any] = {"balances": {}, "balance_error": False}

    async def fake_fetch_balance(**_: Any) -> dict[str, int]:
        """Return the configured balance or raise a provider error."""
        if context["balance_error"]:
            raise PaystackProviderError("Paystack is down")
        return dict(context["balances"])

    monkeypatch.setattr(treasury.paystack, "fetch_balance", fake_fetch_balance)
    try:
        yield context
    finally:
        await _reset()
        await engine.dispose()


async def _user(role: str) -> UUID:
    """Create a verified user holding one approved role."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{role}-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name=role.title(),
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC))
            )
        return user.id


def _headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for a user with the given roles."""
    return {
        "Authorization": f"Bearer {create_access_token(user_id=user_id, roles=roles)}"
    }


async def _seed_ledger() -> dict[str, UUID]:
    """Seed one NGN ledger covering every summary line.

    Contributor: a cleared ₦10,000 sale (₦1,500 commission), a refunded sale,
    a completed ₦3,000 payout and an in-flight ₦2,000 payout.
    Org: a released ₦150,000 attestation fee (₦15,000 commission).
    Milestone: ₦100,000 still held in escrow (commission not yet earned).
    Partner: a pending ₦500 commission on the contributor's sale.
    Paystack kept a ₦250 fee.
    """
    operator_id = await _user("operator")
    contributor_id = await _user("contributor")
    developer_id = await _user("developer")
    old = datetime.now(UTC) - timedelta(days=30)
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:8]}",
                name="Ikeji Advisory",
                country="NG",
                created_by=contributor_id,
            )
            session.add(org)
            framework = Framework(
                contributor_id=contributor_id,
                title="Vendor Risk Framework",
                description="Framework sold in the treasury ledger seed.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["treasury"],
                price=Decimal("10000.00"),
                currency="NGN",
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()

            sale = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("10000.00"),
                currency="NGN",
                platform_commission=Decimal("1500.00"),
                net_amount=Decimal("8500.00"),
                transaction_type="purchase",
                status="completed",
                provider="paystack",
                provider_ref="sale-1",
                ref_id=framework.id,
                ref_type="framework",
                created_at=old,
            )
            refunded = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("5000.00"),
                currency="NGN",
                platform_commission=Decimal("750.00"),
                net_amount=Decimal("4250.00"),
                transaction_type="purchase",
                status="refunded",
                provider="paystack",
                provider_ref="sale-2",
                ref_id=uuid4(),
                ref_type="framework",
                created_at=old,
            )
            attestation_ref = uuid4()
            attestation_fee = Transaction(
                payer_id=operator_id,
                payee_org_id=org.id,
                amount=Decimal("150000.00"),
                currency="NGN",
                platform_commission=Decimal("15000.00"),
                net_amount=Decimal("135000.00"),
                transaction_type="attestation_fee",
                status="completed",
                provider="paystack",
                provider_ref="att-1",
                ref_id=attestation_ref,
                ref_type="attestation",
            )
            milestone_ref = uuid4()
            milestone = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("100000.00"),
                currency="NGN",
                platform_commission=Decimal("15000.00"),
                net_amount=Decimal("85000.00"),
                transaction_type="milestone",
                status="completed",
                provider="paystack",
                provider_ref="ms-1",
                ref_id=milestone_ref,
                ref_type="project_milestone",
            )
            session.add_all([sale, refunded, attestation_fee, milestone])
            await session.flush()
            session.add_all(
                [
                    Escrow(
                        ref_id=attestation_ref,
                        ref_type="attestation",
                        amount=Decimal("150000.00"),
                        currency="NGN",
                        status="released",
                        transaction_id=attestation_fee.id,
                    ),
                    Escrow(
                        ref_id=milestone_ref,
                        ref_type="project_milestone",
                        amount=Decimal("100000.00"),
                        currency="NGN",
                        status="held",
                        transaction_id=milestone.id,
                    ),
                ]
            )

            account = PayoutAccount(
                user_id=contributor_id,
                provider="paystack",
                provider_account_id="RCP_test",
                provider_account_lookup_hash=f"hash-{uuid4()}",
                account_type="bank",
                verified_at=datetime.now(UTC),
            )
            session.add(account)
            await session.flush()
            for net, payout_status in (
                (Decimal("3000.00"), "completed"),
                (Decimal("2000.00"), "processing"),
            ):
                session.add(
                    Payout(
                        contributor_id=contributor_id,
                        payout_account_id=account.id,
                        amount=net,
                        currency="NGN",
                        commission_deducted=Decimal("0.00"),
                        net_amount=net,
                        status=payout_status,
                    )
                )

            application = DeveloperApplication(
                user_id=developer_id,
                company_name="Lagos Partner",
                website="https://lagos-partner.example.com",
                use_case="Resell frameworks.",
                status="approved",
                reviewed_at=datetime.now(UTC),
            )
            session.add(application)
            await session.flush()
            developer = DeveloperAccount(
                user_id=developer_id,
                application_id=application.id,
                company_name="Lagos Partner",
                commission_tier=1,
                tier_rate=Decimal("0.0500"),
            )
            session.add(developer)
            await session.flush()
            api_key = ApiKey(
                developer_account_id=developer.id,
                name="Treasury key",
                key_prefix="ak_trsy",
                key_hash=f"treasury-hash-{uuid4()}",
                scopes=["purchase:write"],
            )
            session.add(api_key)
            await session.flush()
            session.add(
                PartnerCommission(
                    api_key_id=api_key.id,
                    developer_account_id=developer.id,
                    transaction_id=sale.id,
                    framework_id=sale.ref_id,
                    sale_amount=Decimal("10000.00"),
                    currency="NGN",
                    tier_at_sale=1,
                    tier_rate=Decimal("0.0500"),
                    commission_amount=Decimal("500.00"),
                    status="pending",
                )
            )
            session.add(
                ProviderFee(
                    provider="paystack",
                    source_type="transaction",
                    source_id=sale.id,
                    amount=Decimal("250.00"),
                    currency="NGN",
                    provider_ref="sale-1",
                    origin="webhook",
                )
            )
    return {"contributor_id": contributor_id, "org_id": org.id}


def _ngn(body: dict[str, Any]) -> dict[str, Any]:
    """Return the NGN block of a summary response."""
    return next(item for item in body["currencies"] if item["currency"] == "NGN")


async def test_summary_splits_users_money_from_ours(
    client: AsyncClient,
    treasury_context: dict[str, Any],
) -> None:
    """Every liability and platform-money line matches the seeded ledger."""
    await _seed_ledger()
    treasury_context["balances"] = {"NGN": 25_900_000}
    admin_id = await _user("admin")

    response = await client.get(SUMMARY_PATH, headers=_headers(admin_id, ["admin"]))

    assert response.status_code == 200
    ngn = _ngn(response.json())
    assert ngn["withdrawable_here"] is True
    assert ngn["owed_to_users"] == {
        "held_escrow": "100000.00",
        "contributor_balances": "5500.00",
        "org_balances": "135000.00",
        "partner_commissions": "500.00",
        "total": "241000.00",
    }
    assert ngn["our_money"] == {
        "commission_framework_sales": "1500.00",
        "commission_collections": "0.00",
        "commission_project_milestones": "0.00",
        "commission_attestation_fees": "15000.00",
        "provider_fees": "250.00",
        "partner_commissions": "500.00",
        "platform_withdrawals": "0.00",
        "total": "15750.00",
    }
    assert ngn["live_balance"] == "259000.00"
    assert ngn["balance_unavailable"] is False
    # min(our money 15,750, balance 259,000 − owed 241,000 = 18,000)
    assert ngn["withdrawable"] == "15750.00"
    # 259,000 − (241,000 + 15,750)
    assert ngn["balance_gap"] == "2250.00"


async def test_withdrawable_is_capped_by_what_the_balance_can_spare(
    client: AsyncClient,
    treasury_context: dict[str, Any],
) -> None:
    """A short balance caps withdrawal below our money and shows a negative gap."""
    await _seed_ledger()
    treasury_context["balances"] = {"NGN": 25_000_000}
    admin_id = await _user("admin")

    response = await client.get(SUMMARY_PATH, headers=_headers(admin_id, ["admin"]))

    ngn = _ngn(response.json())
    assert ngn["withdrawable"] == "9000.00"
    assert ngn["balance_gap"] == "-6750.00"


async def test_withdrawable_never_goes_negative(
    client: AsyncClient,
    treasury_context: dict[str, Any],
) -> None:
    """A balance below what users are owed leaves nothing withdrawable."""
    await _seed_ledger()
    treasury_context["balances"] = {"NGN": 10_000_000}
    admin_id = await _user("admin")

    response = await client.get(SUMMARY_PATH, headers=_headers(admin_id, ["admin"]))

    assert _ngn(response.json())["withdrawable"] == "0.00"


async def test_balance_outage_still_returns_the_ledger(
    client: AsyncClient,
    treasury_context: dict[str, Any],
) -> None:
    """Without a live balance nothing is withdrawable, but the ledger still shows."""
    await _seed_ledger()
    treasury_context["balance_error"] = True
    admin_id = await _user("admin")

    response = await client.get(SUMMARY_PATH, headers=_headers(admin_id, ["admin"]))

    assert response.status_code == 200
    ngn = _ngn(response.json())
    assert ngn["balance_unavailable"] is True
    assert ngn["live_balance"] is None
    assert ngn["withdrawable"] is None
    assert ngn["balance_gap"] is None
    assert ngn["owed_to_users"]["total"] == "241000.00"


async def test_contributor_line_matches_the_payout_flow_balance(
    treasury_context: dict[str, Any],
) -> None:
    """The aggregate uses the payout flow's own rules, not a second definition.

    With every sale cleared, what the contributor could still withdraw plus
    what is already in flight must equal what Treasury says they are owed.
    """
    ids = await _seed_ledger()
    async with async_session_factory() as session:
        (
            _,
            pending,
            available,
            _,
            _,
        ) = await financials_service._available_payout_balance(
            session, contributor_id=ids["contributor_id"], currency="NGN"
        )
        summary = await treasury.get_treasury_summary(session)

    ngn = next(item for item in summary.currencies if item.currency == "NGN")
    in_flight = Decimal("2000.00")
    assert pending == Decimal("0.00")
    assert ngn.owed_to_users.contributor_balances == available + in_flight


async def test_non_paystack_currency_is_ledger_only(
    client: AsyncClient,
    treasury_context: dict[str, Any],
) -> None:
    """Stripe money is listed but never offered for withdrawal here."""
    operator_id = await _user("operator")
    contributor_id = await _user("contributor")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Transaction(
                    payer_id=operator_id,
                    payee_id=contributor_id,
                    amount=Decimal("149.00"),
                    currency="USD",
                    platform_commission=Decimal("22.35"),
                    net_amount=Decimal("126.65"),
                    transaction_type="purchase",
                    status="completed",
                    provider="stripe",
                    provider_ref="pi_usd",
                    ref_id=uuid4(),
                    ref_type="framework",
                )
            )
    treasury_context["balances"] = {"NGN": 0}
    admin_id = await _user("admin")

    response = await client.get(SUMMARY_PATH, headers=_headers(admin_id, ["admin"]))

    usd = next(i for i in response.json()["currencies"] if i["currency"] == "USD")
    assert usd["withdrawable_here"] is False
    assert usd["live_balance"] is None
    assert usd["withdrawable"] is None
    assert usd["balance_gap"] is None
    assert usd["our_money"]["commission_framework_sales"] == "22.35"


async def test_summary_requires_an_admin(
    client: AsyncClient,
    treasury_context: dict[str, Any],
) -> None:
    """Anonymous callers get 401 and non-admins get 403."""
    operator_id = await _user("operator")

    anonymous = await client.get(SUMMARY_PATH)
    operator = await client.get(
        SUMMARY_PATH, headers=_headers(operator_id, ["operator"])
    )

    assert anonymous.status_code == 401
    assert operator.status_code == 403
