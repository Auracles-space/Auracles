"""Annual attestor earnings summary helpers and PDF rendering.

Annual summaries are derived documents, not ledger invoices. They aggregate
closed attestation fee earnings for one attestor over a prior calendar year and
render a deterministic PDF stored in private S3.

Earnings are attributed to the calendar year of `Attestation.closed_at`, which
is the attestation settlement timestamp in this workflow.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from jinja2 import Environment
from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML  # type: ignore[import-untyped]

from app.core.database import async_session_factory
from app.modules.attestation.models import Attestation
from app.modules.financials.models import PlatformConfig, Transaction
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgMember,
)

_CENTS = Decimal("0.01")
_TEMPLATE_ENV = Environment(autoescape=True)
_ANNUAL_TEMPLATE = _TEMPLATE_ENV.from_string(
    """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>
          @page { size: A4; margin: 24px; }
          body { font-family: sans-serif; color: #171717; }
          h1 { margin-bottom: 4px; }
          .muted { color: #5f6368; }
          table { width: 100%; border-collapse: collapse; margin-top: 24px; }
          th, td {
            text-align: left;
            padding: 10px 0;
            border-bottom: 1px solid #ece7df;
          }
          .amount { text-align: right; }
          .summary { width: 360px; margin-left: auto; margin-top: 24px; }
          .summary td { border-bottom: none; }
          .summary .total td { border-top: 2px solid #171717; font-weight: 700; }
        </style>
      </head>
      <body>
        <h1>Auracles Annual Earnings Summary</h1>
        <p class="muted">{{ attestor_name }} · {{ year }}</p>
        <table>
          <thead>
            <tr>
              <th>Settled</th>
              <th>Attestation</th>
              <th>Review type</th>
              <th class="amount">Gross</th>
              <th class="amount">Rate</th>
              <th class="amount">Net</th>
            </tr>
          </thead>
          <tbody>
          {% for item in line_items %}
            <tr>
              <td>{{ item.settled_at }}</td>
              <td>{{ item.attestation_id }}</td>
              <td>{{ item.review_type }}</td>
              <td class="amount">{{ item.gross_amount }}</td>
              <td class="amount">{{ item.commission_rate }}</td>
              <td class="amount">{{ item.net_amount }}</td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
        <table class="summary">
          <tbody>
            <tr>
              <td>Attestations</td>
              <td class="amount">{{ totals.count }}</td>
            </tr>
            <tr>
              <td>Gross earnings</td>
              <td class="amount">{{ totals.gross_amount }}</td>
            </tr>
            <tr class="total">
              <td>Net earnings</td>
              <td class="amount">{{ totals.net_amount }}</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """
)


def annual_summary_key(attestor_id: UUID, year: int) -> str:
    """Return the deterministic S3 key for one annual summary PDF."""
    return f"annual-summaries/{attestor_id}/{year}.pdf"


async def _attestation_commission_rate(db: AsyncSession) -> Decimal:
    """Return the configured attestation commission rate."""
    value = await db.scalar(
        select(PlatformConfig.value).where(
            PlatformConfig.key == "attestation_commission_rate"
        )
    )
    if value is None:
        return Decimal("0.10")
    return Decimal(value)


def _summarise_rows(
    rows: Sequence[Row[tuple[Attestation, Transaction]]],
    commission_rate: Decimal,
) -> tuple[list[dict[str, str]], dict[str, str | int]]:
    """Build annual summary line items and totals from settled fee rows."""
    line_items: list[dict[str, str]] = []
    gross_total = Decimal("0.00")
    net_total = Decimal("0.00")
    for attestation, transaction in rows:
        gross_amount = Decimal(transaction.amount).quantize(_CENTS)
        net_amount = (gross_amount * (Decimal("1") - commission_rate)).quantize(_CENTS)
        gross_total += gross_amount
        net_total += net_amount
        line_items.append(
            {
                "settled_at": (
                    attestation.closed_at.astimezone(UTC).date().isoformat()
                    if attestation.closed_at is not None
                    else ""
                ),
                "attestation_id": str(attestation.id),
                "review_type": (
                    (attestation.review_type or "attestation").replace("_", " ").title()
                ),
                "gross_amount": f"{gross_amount} {transaction.currency}",
                "commission_rate": f"{(commission_rate * Decimal('100')).normalize()}%",
                "net_amount": f"{net_amount} {transaction.currency}",
            }
        )
    totals: dict[str, str | int] = {
        "count": len(line_items),
        "gross_amount": f"{gross_total.quantize(_CENTS)} USD",
        "net_amount": f"{net_total.quantize(_CENTS)} USD",
    }
    return line_items, totals


def annual_org_summary_key(org_id: UUID, year: int) -> str:
    """Return the deterministic S3 key for one org's annual summary PDF."""
    return f"annual-summaries/org/{org_id}/{year}.pdf"


async def annual_org_earner_ids(db: AsyncSession, year: int) -> list[UUID]:
    """Return orgs with at least one closed attestation fee in the year."""
    year_start = datetime(year, 1, 1, tzinfo=UTC)
    year_end = datetime(year + 1, 1, 1, tzinfo=UTC)
    rows = await db.scalars(
        select(Attestation.attestor_org_id)
        .join(
            Transaction,
            (Transaction.ref_id == Attestation.id)
            & (Transaction.ref_type == "attestation")
            & (Transaction.transaction_type == "attestation_fee"),
        )
        .where(
            Attestation.attestor_org_id.is_not(None),
            Attestation.status == "closed",
            Attestation.closed_at.is_not(None),
            Attestation.closed_at >= year_start,
            Attestation.closed_at < year_end,
        )
        .distinct()
    )
    return [org_id for org_id in rows if org_id is not None]


async def _annual_org_earner_ids(year: int) -> list[UUID]:
    """Open a session and return annual org earner ids for the year."""
    async with async_session_factory() as db:
        return await annual_org_earner_ids(db, year)


async def annual_org_line_items(
    db: AsyncSession,
    *,
    org_id: UUID,
    year: int,
) -> tuple[list[dict[str, str]], dict[str, str | int]]:
    """Return annual summary line items and total rows for one org."""
    year_start = datetime(year, 1, 1, tzinfo=UTC)
    year_end = datetime(year + 1, 1, 1, tzinfo=UTC)
    commission_rate = await _attestation_commission_rate(db)
    rows = (
        await db.execute(
            select(Attestation, Transaction)
            .join(
                Transaction,
                (Transaction.ref_id == Attestation.id)
                & (Transaction.ref_type == "attestation")
                & (Transaction.transaction_type == "attestation_fee"),
            )
            .where(
                Attestation.attestor_org_id == org_id,
                Attestation.status == "closed",
                Attestation.closed_at.is_not(None),
                Attestation.closed_at >= year_start,
                Attestation.closed_at < year_end,
            )
            .order_by(Attestation.closed_at, Attestation.id)
        )
    ).all()
    return _summarise_rows(rows, commission_rate)


async def org_name(db: AsyncSession, org_id: UUID) -> str:
    """Return an org's billing name for its annual summary.

    Prefers the approved application's ``legal_name``, falling back to the
    organization's display name.
    """
    legal_name = await db.scalar(
        select(OrgAttestorApplication.legal_name).where(
            OrgAttestorApplication.org_id == org_id,
            OrgAttestorApplication.status == "approved",
        )
    )
    if legal_name:
        return legal_name
    name = await db.scalar(select(Organization.name).where(Organization.id == org_id))
    if name is None:
        raise ValueError("Organization not found.")
    return name


async def org_owner_id(db: AsyncSession, org_id: UUID) -> UUID | None:
    """Return the owner member's user id for org summary notifications."""
    owner_id: UUID | None = await db.scalar(
        select(OrgMember.user_id)
        .where(OrgMember.org_id == org_id, OrgMember.role == "owner")
        .limit(1)
    )
    return owner_id


def render_annual_summary_pdf(
    *,
    attestor_name: str,
    year: int,
    line_items: list[dict[str, str]],
    totals: dict[str, str | int],
) -> bytes:
    """Render one annual-summary PDF."""
    html = _ANNUAL_TEMPLATE.render(
        attestor_name=attestor_name,
        year=year,
        line_items=line_items,
        totals=totals,
    )
    return bytes(HTML(string=html).write_pdf())
