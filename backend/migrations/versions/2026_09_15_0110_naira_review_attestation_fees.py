"""Reprice framework attestation review fees in naira.

The review fees were seeded in 0044 as dollar-era amounts (500 / 1200 / 2500 /
500). The platform now settles in naira, so a quality review charged ₦500.
Human decision 2026-09-15: quality ₦150,000, compliance ₦350,000, expert
₦750,000, provenance ₦150,000. Only rows still holding the original seed are
changed, so a value an admin already edited is left alone; the downgrade
mirrors that.

Revision ID: 2026_09_15_0110
Revises: 2026_09_15_0109
Create Date: 2026-09-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_09_15_0110"
down_revision: str | Sequence[str] | None = "2026_09_15_0109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# key: (old seed, new naira fee)
REVIEW_FEES = {
    "attestation_fee_review_quality": ("500.00", "150000.00"),
    "attestation_fee_review_compliance": ("1200.00", "350000.00"),
    "attestation_fee_review_expert": ("2500.00", "750000.00"),
    "attestation_fee_review_provenance": ("500.00", "150000.00"),
}

_SWAP = sa.text(
    "UPDATE platform_config SET value = :to_value "
    "WHERE key = :key AND value = :from_value"
)


def upgrade() -> None:
    """Move untouched review fees from the seed amounts to naira."""
    for key, (old, new) in REVIEW_FEES.items():
        op.execute(_SWAP.bindparams(key=key, from_value=old, to_value=new))


def downgrade() -> None:
    """Restore the seed amounts where the naira fee is still in place."""
    for key, (old, new) in REVIEW_FEES.items():
        op.execute(_SWAP.bindparams(key=key, from_value=new, to_value=old))
