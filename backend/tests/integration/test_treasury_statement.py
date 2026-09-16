"""Integration tests for the monthly Treasury statement CSV.

The statement is what the accountant reconciles against the bank, so it has
to add up: closing balance = opening balance + every dated line in the month,
one month's closing is the next month's opening, and the latest month agrees
with the live Treasury summary. Months follow Lagos time.

Maps to: platform treasury design §Statement, decision 11.
"""

from __future__ import annotations

import csv
import io
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
    create_access_token,
    encrypt_payout_provider_account_id,
)
from app.modules.developer.models import (
    ApiKey,
    DeveloperAccount,
    DeveloperApplication,
    PartnerCommission,
)
from app.modules.financials import treasury
from app.modules.financials.models import (
    Escrow,
    FinancialEvent,
    Payout,
    PayoutAccount,
    PlatformBankAccount,
    PlatformWithdrawal,
    ProviderFee,
    Transaction,
)
from app.modules.frameworks.models import Framework
from app.modules.organizations.models import Organization
from app.shared.models.audit_log import AuditLog
from tests.integration.test_admin_treasury_summary import _reset, _user

PATH = "/v1/admin/treasury/statements"
BODY_SECTIONS = {
    "commission",
    "refunds",
    "provider_fees",
    "partner_commissions",
    "withdrawal",
}


def _utc(*parts: int) -> datetime:
    """Build a UTC datetime."""
    return datetime(*parts, tzinfo=UTC)


@pytest.fixture
async def statement_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    """Reset state and pin the live Paystack balance for the summary check."""
    await engine.dispose()
    await _reset()

    async def fake_fetch_balance(**_: Any) -> dict[str, int]:
        """Return an empty balance; the statement never reads it."""
        return {"NGN": 0}

    monkeypatch.setattr(treasury.paystack, "fetch_balance", fake_fetch_balance)
    try:
        yield
    finally:
        await _reset()
        await engine.dispose()


def _headers(user_id: UUID, role: str = "admin") -> dict[str, str]:
    """Build bearer headers for one role."""
    token = create_access_token(user_id=user_id, roles=[role])
    return {"Authorization": f"Bearer {token}"}


async def _seed_two_months() -> None:
    """Seed August and September 2025 (Lagos time) with every statement line.

    August: ₦10,000 sale (₦1,500 commission), ₦5,000 sale (₦750, refunded 3
    September), ₦150,000 attestation fee held 20 August and released 10
    September (₦15,000), ₦250 fee, ₦500 partner commission, ₦3,000 payout.
    September: ₦100,000 milestone still held, ₦5,000 withdrawal.
    """
    operator_id = await _user("operator")
    contributor_id = await _user("contributor")
    developer_id = await _user("developer")
    superadmin_id = await _user("admin")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:8]}",
                name="Ikeji Advisory",
                country="NG",
                created_by=contributor_id,
            )
            framework = Framework(
                contributor_id=contributor_id,
                title="Vendor Risk Framework",
                description="Framework sold in the statement seed.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["statement"],
                price=Decimal("10000.00"),
                currency="NGN",
                license_types=["single_user"],
                published_at=_utc(2025, 8, 1),
            )
            session.add_all([org, framework])
            await session.flush()

            def charge(**kwargs: Any) -> Transaction:
                """Build an NGN Paystack transaction."""
                return Transaction(
                    payer_id=operator_id,
                    currency="NGN",
                    provider="paystack",
                    provider_ref=f"stmt-{uuid4().hex[:8]}",
                    **kwargs,
                )

            sale = charge(
                payee_id=contributor_id,
                amount=Decimal("10000.00"),
                platform_commission=Decimal("1500.00"),
                net_amount=Decimal("8500.00"),
                transaction_type="purchase",
                status="completed",
                ref_id=framework.id,
                ref_type="framework",
                created_at=_utc(2025, 8, 5, 10),
            )
            refunded = charge(
                payee_id=contributor_id,
                amount=Decimal("5000.00"),
                platform_commission=Decimal("750.00"),
                net_amount=Decimal("4250.00"),
                transaction_type="purchase",
                status="refunded",
                ref_id=framework.id,
                ref_type="framework",
                created_at=_utc(2025, 8, 10, 10),
            )
            attestation_ref = uuid4()
            attestation_fee = charge(
                payee_org_id=org.id,
                amount=Decimal("150000.00"),
                platform_commission=Decimal("15000.00"),
                net_amount=Decimal("135000.00"),
                transaction_type="attestation_fee",
                status="completed",
                ref_id=attestation_ref,
                ref_type="attestation",
                created_at=_utc(2025, 8, 20, 10),
            )
            milestone_ref = uuid4()
            milestone = charge(
                payee_id=contributor_id,
                amount=Decimal("100000.00"),
                platform_commission=Decimal("15000.00"),
                net_amount=Decimal("85000.00"),
                transaction_type="milestone",
                status="completed",
                ref_id=milestone_ref,
                ref_type="project_milestone",
                created_at=_utc(2025, 9, 12, 10),
            )
            session.add_all([sale, refunded, attestation_fee, milestone])
            await session.flush()
            session.add_all(
                [
                    FinancialEvent(
                        entity_type="transaction",
                        entity_id=refunded.id,
                        event_type="refund_requested",
                        from_status="completed",
                        to_status="refunded",
                        amount=Decimal("5000.00"),
                        currency="NGN",
                        provider="paystack",
                        occurred_at=_utc(2025, 9, 3, 10),
                    ),
                    Escrow(
                        ref_id=attestation_ref,
                        ref_type="attestation",
                        amount=Decimal("150000.00"),
                        currency="NGN",
                        status="released",
                        transaction_id=attestation_fee.id,
                        held_at=_utc(2025, 8, 20, 10),
                        released_at=_utc(2025, 9, 10, 10),
                    ),
                    Escrow(
                        ref_id=milestone_ref,
                        ref_type="project_milestone",
                        amount=Decimal("100000.00"),
                        currency="NGN",
                        status="held",
                        transaction_id=milestone.id,
                        held_at=_utc(2025, 9, 12, 10),
                    ),
                    ProviderFee(
                        provider="paystack",
                        source_type="transaction",
                        source_id=sale.id,
                        amount=Decimal("250.00"),
                        currency="NGN",
                        provider_ref=sale.provider_ref,
                        origin="webhook",
                        occurred_at=_utc(2025, 8, 5, 10),
                    ),
                ]
            )

            payout_account = PayoutAccount(
                user_id=contributor_id,
                provider="paystack",
                provider_account_id="RCP_stmt",
                provider_account_lookup_hash=f"hash-{uuid4()}",
                account_type="nuban",
                verified_at=_utc(2025, 8, 1),
            )
            session.add(payout_account)
            await session.flush()
            session.add(
                Payout(
                    contributor_id=contributor_id,
                    payout_account_id=payout_account.id,
                    amount=Decimal("3000.00"),
                    currency="NGN",
                    commission_deducted=Decimal("0.00"),
                    net_amount=Decimal("3000.00"),
                    status="completed",
                    initiated_at=_utc(2025, 8, 24, 10),
                    completed_at=_utc(2025, 8, 25, 10),
                )
            )

            application = DeveloperApplication(
                user_id=developer_id,
                company_name="Lagos Partner",
                website="https://lagos-partner.example.com",
                use_case="Resell frameworks.",
                status="approved",
                reviewed_at=_utc(2025, 8, 1),
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
                name="Statement key",
                key_prefix="ak_stmt",
                key_hash=f"statement-hash-{uuid4()}",
                scopes=["purchase:write"],
            )
            session.add(api_key)
            await session.flush()
            session.add(
                PartnerCommission(
                    api_key_id=api_key.id,
                    developer_account_id=developer.id,
                    transaction_id=sale.id,
                    framework_id=framework.id,
                    sale_amount=Decimal("10000.00"),
                    currency="NGN",
                    tier_at_sale=1,
                    tier_rate=Decimal("0.0500"),
                    commission_amount=Decimal("500.00"),
                    status="pending",
                    created_at=_utc(2025, 8, 5, 10),
                )
            )

            bank_account = PlatformBankAccount(
                provider="paystack",
                bank_code="058",
                bank_name="Guaranty Trust Bank",
                account_last4="6789",
                account_name="AURACLES TECHNOLOGIES LTD",
                recipient_code_encrypted=encrypt_payout_provider_account_id("RCP_p"),
                usable_from=_utc(2025, 8, 2),
                created_by=superadmin_id,
            )
            session.add(bank_account)
            await session.flush()
            withdrawal_id = uuid4()
            session.add(
                PlatformWithdrawal(
                    id=withdrawal_id,
                    bank_account_id=bank_account.id,
                    amount=Decimal("5000.00"),
                    currency="NGN",
                    status="completed",
                    provider_ref=f"platform-withdrawal-{withdrawal_id}",
                    requested_by=superadmin_id,
                    requested_at=_utc(2025, 9, 15, 10),
                    completed_at=_utc(2025, 9, 15, 11),
                )
            )


async def _partner_commission(
    *,
    sale_status: str = "completed",
    status: str = "pending",
    created_at: datetime | None = None,
    voided_at: datetime | None = None,
) -> dict[str, UUID]:
    """Create a ₦10,000 sale carrying a ₦500 partner commission."""
    operator_id = await _user("operator")
    contributor_id = await _user("contributor")
    developer_id = await _user("developer")
    moment = created_at or datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Partner Sold Framework",
                description="Framework sold through a partner.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["partner"],
                price=Decimal("10000.00"),
                currency="NGN",
                license_types=["single_user"],
                published_at=moment,
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
                status=sale_status,
                provider="paystack",
                provider_ref=f"pc-{uuid4().hex[:8]}",
                ref_id=framework.id,
                ref_type="framework",
                created_at=moment,
            )
            session.add(sale)
            await session.flush()
            application = DeveloperApplication(
                user_id=developer_id,
                company_name="Abuja Partner",
                website="https://abuja-partner.example.com",
                use_case="Resell frameworks.",
                status="approved",
                reviewed_at=moment,
            )
            session.add(application)
            await session.flush()
            developer = DeveloperAccount(
                user_id=developer_id,
                application_id=application.id,
                company_name="Abuja Partner",
                commission_tier=1,
                tier_rate=Decimal("0.0500"),
            )
            session.add(developer)
            await session.flush()
            api_key = ApiKey(
                developer_account_id=developer.id,
                name="Partner key",
                key_prefix="ak_part",
                key_hash=f"partner-hash-{uuid4()}",
                scopes=["purchase:write"],
            )
            session.add(api_key)
            await session.flush()
            commission = PartnerCommission(
                api_key_id=api_key.id,
                developer_account_id=developer.id,
                transaction_id=sale.id,
                framework_id=framework.id,
                sale_amount=Decimal("10000.00"),
                currency="NGN",
                tier_at_sale=1,
                tier_rate=Decimal("0.0500"),
                commission_amount=Decimal("500.00"),
                status=status,
                created_at=moment,
                voided_at=voided_at,
            )
            session.add(commission)
            await session.flush()
            return {
                "commission_id": commission.id,
                "transaction_id": sale.id,
                "operator_id": operator_id,
            }


def _rows(body: str) -> list[dict[str, str]]:
    """Parse the statement CSV."""
    return list(csv.DictReader(io.StringIO(body)))


def _value(rows: list[dict[str, str]], section: str, line: str) -> str:
    """Return the amount of the one row with this section and line."""
    matches = [r for r in rows if r["section"] == section and r["line"] == line]
    assert len(matches) == 1, (section, line, matches)
    return matches[0]["amount"]


async def test_august_statement_lines_and_month_end_users_money(
    client: AsyncClient,
    statement_context: None,
) -> None:
    """August shows its own lines and what users were owed at its end."""
    await _seed_two_months()
    admin_id = await _user("admin")

    response = await client.get(f"{PATH}/2025-08", headers=_headers(admin_id))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert (
        "auracles-treasury-NGN-2025-08.csv" in (response.headers["content-disposition"])
    )
    rows = _rows(response.text)
    assert _value(rows, "opening_balance", "our_money") == "0.00"
    assert _value(rows, "commission", "framework_sales") == "2250.00"
    assert _value(rows, "commission", "attestation_fees") == "0.00"
    assert _value(rows, "refunds", "commission_reversed") == "0.00"
    assert _value(rows, "provider_fees", "paystack") == "-250.00"
    assert _value(rows, "partner_commissions", "partner_commissions") == "-500.00"
    assert [r for r in rows if r["section"] == "withdrawal"] == []
    assert _value(rows, "closing_balance", "our_money") == "1500.00"
    # The attestation fee was still in escrow and the refunded sale still owed.
    assert _value(rows, "users_money", "held_escrow") == "150000.00"
    assert _value(rows, "users_money", "contributor_balances") == "9750.00"
    assert _value(rows, "users_money", "org_balances") == "0.00"
    assert _value(rows, "users_money", "partner_commissions") == "500.00"
    assert _value(rows, "users_money", "total") == "160250.00"


async def test_september_opens_where_august_closed_and_adds_up(
    client: AsyncClient,
    statement_context: None,
) -> None:
    """September's opening is August's closing, and its closing adds up."""
    await _seed_two_months()
    admin_id = await _user("admin")

    response = await client.get(f"{PATH}/2025-09", headers=_headers(admin_id))

    rows = _rows(response.text)
    assert _value(rows, "opening_balance", "our_money") == "1500.00"
    assert _value(rows, "commission", "attestation_fees") == "15000.00"
    assert _value(rows, "commission", "project_milestones") == "0.00"
    assert _value(rows, "refunds", "commission_reversed") == "-750.00"
    withdrawals = [r for r in rows if r["section"] == "withdrawal"]
    assert len(withdrawals) == 1
    assert withdrawals[0]["amount"] == "-5000.00"
    assert withdrawals[0]["date"] == "2025-09-15"
    assert withdrawals[0]["reference"].startswith("platform-withdrawal-")
    assert withdrawals[0]["line"] == "completed ****6789"
    closing = Decimal(_value(rows, "closing_balance", "our_money"))
    body_lines = sum(
        Decimal(r["amount"])
        for r in rows
        if r["section"]
        in {
            "commission",
            "refunds",
            "provider_fees",
            "partner_commissions",
            "withdrawal",
        }
    )
    assert closing == Decimal("1500.00") + body_lines == Decimal("10750.00")
    assert _value(rows, "users_money", "held_escrow") == "100000.00"
    assert _value(rows, "users_money", "contributor_balances") == "5500.00"
    assert _value(rows, "users_money", "org_balances") == "135000.00"


async def test_the_latest_statement_agrees_with_the_live_summary(
    client: AsyncClient,
    statement_context: None,
) -> None:
    """With nothing after September, its closing figures match Treasury now."""
    await _seed_two_months()
    admin_id = await _user("admin")

    statement = _rows(
        (await client.get(f"{PATH}/2025-09", headers=_headers(admin_id))).text
    )
    summary = (
        await client.get("/v1/admin/treasury/summary", headers=_headers(admin_id))
    ).json()

    ngn = next(i for i in summary["currencies"] if i["currency"] == "NGN")
    assert (
        _value(statement, "closing_balance", "our_money") == ngn["our_money"]["total"]
    )
    assert _value(statement, "users_money", "total") == ngn["owed_to_users"]["total"]


async def test_months_follow_lagos_time(
    client: AsyncClient,
    statement_context: None,
) -> None:
    """A sale at 23:30 UTC on 31 August is 00:30 on 1 September in Lagos."""
    operator_id = await _user("operator")
    admin_id = await _user("admin")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Transaction(
                    payer_id=operator_id,
                    amount=Decimal("1000.00"),
                    currency="NGN",
                    platform_commission=Decimal("150.00"),
                    net_amount=Decimal("850.00"),
                    transaction_type="purchase",
                    status="completed",
                    provider="paystack",
                    provider_ref="stmt-boundary",
                    ref_id=uuid4(),
                    ref_type="framework",
                    created_at=_utc(2025, 8, 31, 23, 30),
                )
            )

    august = _rows(
        (await client.get(f"{PATH}/2025-08", headers=_headers(admin_id))).text
    )
    september = _rows(
        (await client.get(f"{PATH}/2025-09", headers=_headers(admin_id))).text
    )

    assert _value(august, "commission", "framework_sales") == "0.00"
    assert _value(september, "commission", "framework_sales") == "150.00"


async def test_download_is_audited_and_admin_only(
    client: AsyncClient,
    statement_context: None,
) -> None:
    """Admins download (audited); others are refused; future months are 422."""
    admin_id = await _user("admin")
    operator_id = await _user("operator")

    ok = await client.get(f"{PATH}/2025-08", headers=_headers(admin_id))
    operator = await client.get(
        f"{PATH}/2025-08", headers=_headers(operator_id, "operator")
    )
    future = await client.get(f"{PATH}/2099-01", headers=_headers(admin_id))
    malformed = await client.get(f"{PATH}/2025-13", headers=_headers(admin_id))

    assert ok.status_code == 200
    assert operator.status_code == 403
    assert future.status_code == 422
    assert malformed.status_code == 422
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "treasury_statement_downloaded")
        )
    assert audit is not None
    assert audit.actor_id == admin_id
    assert audit.metadata_ == {"month": "2025-08", "currency": "NGN"}


async def test_a_refunded_escrow_stays_held_in_the_months_before_its_refund(
    client: AsyncClient,
    statement_context: None,
) -> None:
    """Held 25 August, refunded 20 September: held at August end, not September."""
    operator_id = await _user("operator")
    admin_id = await _user("admin")
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=operator_id,
                amount=Decimal("20000.00"),
                currency="NGN",
                platform_commission=Decimal("3000.00"),
                net_amount=Decimal("17000.00"),
                transaction_type="milestone",
                status="refunded",
                provider="paystack",
                provider_ref="stmt-refunded-escrow",
                ref_id=uuid4(),
                ref_type="project_milestone",
                created_at=_utc(2025, 8, 25, 10),
            )
            session.add(transaction)
            await session.flush()
            session.add(
                Escrow(
                    ref_id=transaction.ref_id,
                    ref_type="project_milestone",
                    amount=Decimal("20000.00"),
                    currency="NGN",
                    status="refunded",
                    transaction_id=transaction.id,
                    held_at=_utc(2025, 8, 25, 10),
                    refunded_at=_utc(2025, 9, 20, 10),
                )
            )

    august = _rows(
        (await client.get(f"{PATH}/2025-08", headers=_headers(admin_id))).text
    )
    september = _rows(
        (await client.get(f"{PATH}/2025-09", headers=_headers(admin_id))).text
    )

    assert _value(august, "users_money", "held_escrow") == "20000.00"
    assert _value(september, "users_money", "held_escrow") == "0.00"


async def test_a_voided_partner_commission_counts_until_it_is_voided(
    client: AsyncClient,
    statement_context: None,
) -> None:
    """Created 5 August, voided 5 September: a cost in August, returned in September."""
    admin_id = await _user("admin")
    await _partner_commission(
        sale_status="refunded",
        status="voided",
        created_at=_utc(2025, 8, 5, 10),
        voided_at=_utc(2025, 9, 5, 10),
    )

    august = _rows(
        (await client.get(f"{PATH}/2025-08", headers=_headers(admin_id))).text
    )
    september = _rows(
        (await client.get(f"{PATH}/2025-09", headers=_headers(admin_id))).text
    )

    assert _value(august, "partner_commissions", "partner_commissions") == "-500.00"
    assert _value(august, "partner_commissions", "voided") == "0.00"
    assert _value(august, "users_money", "partner_commissions") == "500.00"
    assert _value(september, "partner_commissions", "partner_commissions") == "0.00"
    assert _value(september, "partner_commissions", "voided") == "500.00"
    assert _value(september, "users_money", "partner_commissions") == "0.00"
    september_closing = Decimal(_value(september, "closing_balance", "our_money"))
    september_opening = Decimal(_value(september, "opening_balance", "our_money"))
    body = sum(Decimal(r["amount"]) for r in september if r["section"] in BODY_SECTIONS)
    assert september_closing == september_opening + body
