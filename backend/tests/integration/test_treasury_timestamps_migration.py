"""Migration test: escrows.refunded_at and partner_commissions.voided_at backfill.

Rows refunded or voided before the columns existed must get their real time
from the ledger (``escrow_refunded`` events) and the audit log
(``partner_commission_voided``), so past statements stay correct.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app.core.database import async_session_factory, engine
from app.main import app
from app.modules.financials.models import Escrow, FinancialEvent, Transaction
from app.shared.models.audit_log import AuditLog
from tests.integration.test_admin_treasury_summary import _reset, _user
from tests.integration.test_treasury_statement import _partner_commission

BACKEND_DIR = Path(__file__).resolve().parents[2]
DOWN = "2026_09_16_0114"
REFUNDED_AT = datetime(2025, 9, 20, 10, tzinfo=UTC)
VOIDED_AT = datetime(2025, 9, 5, 10, tzinfo=UTC)


@pytest.fixture
def alembic_config() -> Iterator[Config]:
    """Alembic config rooted at the backend; always returns to head."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    try:
        yield cfg
    finally:
        command.upgrade(cfg, "head")


async def test_backfill_takes_times_from_ledger_and_audit_log(
    alembic_config: Config,
) -> None:
    """Existing refunded escrows and voided commissions get their event times."""
    await engine.dispose()
    await _reset()
    operator_id = await _user("operator")
    ids = await _partner_commission(sale_status="refunded", status="voided")
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
                provider_ref="mig-refunded-escrow",
                ref_id=ids["transaction_id"],
                ref_type="project_milestone",
            )
            session.add(transaction)
            await session.flush()
            escrow = Escrow(
                ref_id=transaction.ref_id,
                ref_type="project_milestone",
                amount=Decimal("20000.00"),
                currency="NGN",
                status="refunded",
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            session.add_all(
                [
                    FinancialEvent(
                        entity_type="escrow",
                        entity_id=escrow.id,
                        event_type="escrow_refunded",
                        from_status="held",
                        to_status="refunded",
                        amount=Decimal("20000.00"),
                        currency="NGN",
                        occurred_at=REFUNDED_AT,
                    ),
                    AuditLog(
                        actor_id=None,
                        action="partner_commission_voided",
                        target_type="partner_commission",
                        target_id=ids["commission_id"],
                        metadata_={},
                        created_at=VOIDED_AT,
                    ),
                ]
            )
            escrow_id = escrow.id
    await engine.dispose()

    command.downgrade(alembic_config, DOWN)
    command.upgrade(alembic_config, "head")

    sync_engine = create_engine(app.state.settings.sync_database_url)
    try:
        with sync_engine.connect() as conn:
            refunded_at = conn.scalar(
                sa.text("SELECT refunded_at FROM escrows WHERE id = :id"),
                {"id": escrow_id},
            )
            voided_at = conn.scalar(
                sa.text("SELECT voided_at FROM partner_commissions WHERE id = :id"),
                {"id": ids["commission_id"]},
            )
    finally:
        sync_engine.dispose()
        await _reset()
        await engine.dispose()

    assert refunded_at == REFUNDED_AT
    assert voided_at == VOIDED_AT
