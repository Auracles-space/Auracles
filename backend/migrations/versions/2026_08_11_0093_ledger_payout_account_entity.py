"""Allow payout_account as a financial ledger entity type.

Stripe Connect delivers `payout.failed` for a connected account's own bank
payout, and that event carries the only failure code available on the payout
path (`transfer.reversed`, the event Stripe emits when our transfer is undone,
carries none). It identifies the connected account, not one of our payout rows:
a connected account's bank payout can settle several of our transfers at once,
so attributing the failure to a single `payouts` row would be a guess.

Recording it against the payout account instead keeps the ledger truthful.

Maps to: FR-FIN-* payment traceability.

Revision ID: 2026_08_11_0093
Revises: 2026_08_11_0092
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_08_11_0093"
down_revision: str | Sequence[str] | None = "2026_08_11_0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_financial_events_entity_type"
_PREVIOUS = (
    "transaction",
    "escrow",
    "payout",
    "partner_commission",
    "partner_payout",
)
_CURRENT = (*_PREVIOUS, "payout_account")


def _values(entity_types: tuple[str, ...]) -> str:
    """Render entity types as a SQL IN-list literal."""
    return ", ".join(f"'{value}'" for value in entity_types)


def upgrade() -> None:
    """Widen the entity type check to accept payout_account."""
    op.drop_constraint(_CONSTRAINT, "financial_events", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "financial_events",
        f"entity_type IN ({_values(_CURRENT)})",
    )


def downgrade() -> None:
    """Restore the narrower entity type check.

    Rows recorded against a payout account are removed first, since they cannot
    satisfy the restored constraint. This is lossy by nature: the alternative is
    a downgrade that fails outright on any database that has recorded one.
    """
    op.execute("DELETE FROM financial_events WHERE entity_type = 'payout_account'")
    op.drop_constraint(_CONSTRAINT, "financial_events", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "financial_events",
        f"entity_type IN ({_values(_PREVIOUS)})",
    )
