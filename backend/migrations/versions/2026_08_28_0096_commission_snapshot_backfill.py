"""Backfill the sale-time commission snapshot onto existing transactions.

Settlement now stamps `platform_commission` and `net_amount` when a purchase
completes or an escrow funding is held, and balances read the stamped values
(BR-FIN-001 with a sale-time rate snapshot). Every historical earning
transaction predates the stamping and still carries commission 0.00 with
net == amount, which the new balance math would read as commission-free
earnings — so each is stamped here at the currently configured rate, the
best available approximation of its sale-time rate.

Purchases and milestones stamp the marketplace `commission_rate`
(default 0.15); attestation fees stamp `attestation_commission_rate`
(default 0.10). Rows are stamped across all statuses so pending attempts
that later settle through a replayed webhook agree with their siblings;
settlement re-stamps on the transition into completed either way. Refund
and payout transaction rows carry no seller commission and are untouched.

The downgrade restores the pre-snapshot shape (commission 0, net == amount)
for exactly the rows the upgrade stamped, keeping `alembic downgrade -1`
faithful.

Maps to: BR-FIN-001, FR-FIN-010.

Revision ID: 2026_08_28_0096
Revises: 2026_08_12_0095
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_08_28_0096"
down_revision: str | Sequence[str] | None = "2026_08_12_0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fallbacks matching app.modules.financials.commission when the config rows
# are absent from platform_config.
_MARKETPLACE_DEFAULT = "0.15"
_ATTESTATION_DEFAULT = "0.10"

_MARKETPLACE_RATE_SQL = (
    "COALESCE((SELECT value::numeric FROM platform_config "
    f"WHERE key = 'commission_rate'), {_MARKETPLACE_DEFAULT})"
)
_ATTESTATION_RATE_SQL = (
    "COALESCE((SELECT value::numeric FROM platform_config "
    f"WHERE key = 'attestation_commission_rate'), {_ATTESTATION_DEFAULT})"
)


def upgrade() -> None:
    """Stamp unstamped earning transactions at the configured rates."""
    op.execute(
        "UPDATE transactions SET "
        f"platform_commission = round(amount * ({_MARKETPLACE_RATE_SQL}), 2), "
        f"net_amount = amount - round(amount * ({_MARKETPLACE_RATE_SQL}), 2) "
        "WHERE type IN ('purchase', 'milestone') "
        "AND platform_commission = 0 AND net_amount = amount"
    )
    op.execute(
        "UPDATE transactions SET "
        f"platform_commission = round(amount * ({_ATTESTATION_RATE_SQL}), 2), "
        f"net_amount = amount - round(amount * ({_ATTESTATION_RATE_SQL}), 2) "
        "WHERE type = 'attestation_fee' "
        "AND platform_commission = 0 AND net_amount = amount"
    )


def downgrade() -> None:
    """Restore the pre-snapshot commission shape on stamped earning rows."""
    op.execute(
        "UPDATE transactions SET platform_commission = 0, net_amount = amount "
        "WHERE type IN ('purchase', 'milestone', 'attestation_fee') "
        "AND platform_commission > 0 "
        "AND net_amount = amount - platform_commission"
    )
