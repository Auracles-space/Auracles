"""Allow a Framework to be listed free.

`ck_frameworks_price_positive` required every Framework to carry a price above
zero, so a Contributor could only ever enter an amount. Listing something at no
charge was unexpressible, which also ruled out the open-core shape of a
Framework that is free for individuals and paid for Organizations.

Both price constraints move from `> 0` to `>= 0`. The organizational price
stays nullable, and NULL keeps its existing meaning of "reuse the base price" —
distinct from an explicit zero, which is a deliberately free org tier.

The money tables are untouched: a free acquisition writes no transaction, so
`ck_transactions_amount_positive` still guards every charge.

Revision ID: 2026_10_03_0125
Revises: 2026_09_29_0124
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_10_03_0125"
down_revision: str | None = "2026_09_29_0124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Relax both Framework price constraints to admit zero."""
    op.drop_constraint(
        "ck_frameworks_price_positive",
        "frameworks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_frameworks_price_positive",
        "frameworks",
        "price >= 0",
    )
    op.drop_constraint(
        "ck_frameworks_org_price_positive",
        "frameworks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_frameworks_org_price_positive",
        "frameworks",
        "org_price IS NULL OR org_price >= 0",
    )


def downgrade() -> None:
    """Restore the paid-only constraints.

    Any Framework already listed free violates the restored constraint, so the
    rows are moved off zero first. There is no prior price to restore them to,
    so they are withdrawn from sale rather than silently given a price their
    seller never set.
    """
    op.execute(
        """
        UPDATE frameworks
        SET status = 'unpublished',
            price = 0.01
        WHERE price = 0
        """
    )
    op.execute(
        """
        UPDATE frameworks
        SET org_price = NULL
        WHERE org_price = 0
        """
    )
    op.drop_constraint(
        "ck_frameworks_price_positive",
        "frameworks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_frameworks_price_positive",
        "frameworks",
        "price > 0",
    )
    op.drop_constraint(
        "ck_frameworks_org_price_positive",
        "frameworks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_frameworks_org_price_positive",
        "frameworks",
        "org_price IS NULL OR org_price > 0",
    )
