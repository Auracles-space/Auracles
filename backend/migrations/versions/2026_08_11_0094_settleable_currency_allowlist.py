"""Widen the money-table currency checks from USD-only to a settleable set.

Auracles is a single-currency marketplace, but the currency is now a
deployment setting (`PLATFORM_CURRENCY`, see app/core/currency.py) rather than
a literal. The closed Nigerian pilot settles in NGN: Nigerian buyers pay naira
and Nigerian contributors are paid naira, so no conversion exists anywhere in
the money path.

Five tables pinned `currency = 'USD'` at the database level, which would reject
every row the pilot writes. They are widened to the set of currencies the
payment adapters can actually settle. The constraint stays an allowlist rather
than being dropped: it is the last line of defence against a row landing in a
currency no provider can charge, which would strand the money it represents.

Maps to: FR-FIN-* single-currency settlement.

Revision ID: 2026_08_11_0094
Revises: 2026_08_11_0093
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_08_11_0094"
down_revision: str | Sequence[str] | None = "2026_08_11_0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must stay in step with SUPPORTED_MINOR_UNIT_CURRENCIES in
# app/integrations/amounts.py — the set the provider adapters can convert.
_SETTLEABLE = ("USD", "NGN")

# (table, old constraint name, new constraint name)
_TABLES = (
    ("projects", "ck_projects_currency_usd", "ck_projects_currency_settleable"),
    ("proposals", "ck_proposals_currency_usd", "ck_proposals_currency_settleable"),
    ("milestones", "ck_milestones_currency_usd", "ck_milestones_currency_settleable"),
    (
        "attestations",
        "ck_attestations_currency_usd",
        "ck_attestations_currency_settleable",
    ),
    (
        "framework_collections",
        "ck_framework_collections_currency_usd",
        "ck_framework_collections_currency_settleable",
    ),
)


def _values() -> str:
    """Render the settleable currencies as a SQL IN-list literal."""
    return ", ".join(f"'{code}'" for code in _SETTLEABLE)


def upgrade() -> None:
    """Replace each USD-only currency check with the settleable allowlist."""
    for table, old_name, new_name in _TABLES:
        op.drop_constraint(old_name, table, type_="check")
        op.create_check_constraint(new_name, table, f"currency IN ({_values()})")


def downgrade() -> None:
    """Restore the USD-only currency checks.

    Rows in any other currency are deleted first: they cannot satisfy the
    restored constraint, and leaving them would make the downgrade fail outright
    on any database that has taken a non-USD payment. This is lossy by nature —
    do not downgrade past this revision once the pilot has traded.
    """
    for table, old_name, new_name in _TABLES:
        op.execute(f"DELETE FROM {table} WHERE currency <> 'USD'")  # noqa: S608
        op.drop_constraint(new_name, table, type_="check")
        op.create_check_constraint(old_name, table, "currency = 'USD'")
