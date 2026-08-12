"""Raise the NGN payout floor to the figure the pilot launches on.

`min_payout_ngn` was seeded at 20,000 by 0009 as a placeholder, back when
Paystack payouts were deferred and nothing read the value. The closed Nigerian
pilot settles in NGN, so this is now the number that decides whether a
Contributor can withdraw at all, and it is 50,000.

The row is only updated where it still holds the placeholder: an operator who
has already tuned the floor through the admin console has made a decision this
migration must not overwrite. The key is admin-editable from this revision on
(see EDITABLE_PLATFORM_CONFIG_KEYS), so it is expected to drift from the seed.

Maps to: FR-FIN-012.

Revision ID: 2026_08_12_0095
Revises: 2026_08_11_0094
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_08_12_0095"
down_revision: str | Sequence[str] | None = "2026_08_11_0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLACEHOLDER = "20000"
_PILOT_FLOOR = "50000"


def upgrade() -> None:
    """Move the untouched placeholder floor to the pilot figure."""
    op.execute(
        "UPDATE platform_config "
        f"SET value = '{_PILOT_FLOOR}' "
        f"WHERE key = 'min_payout_ngn' AND value = '{_PLACEHOLDER}'"
    )


def downgrade() -> None:
    """Restore the placeholder, leaving any admin-set floor alone."""
    op.execute(
        "UPDATE platform_config "
        f"SET value = '{_PLACEHOLDER}' "
        f"WHERE key = 'min_payout_ngn' AND value = '{_PILOT_FLOOR}'"
    )
