"""Org beneficiary on payouts for org-attested earnings settlement.

Organizations-as-Attestors settlement (sub-project 2, Task 8) routes an org's
released attestation fees to an org-owned payout. Task 2 gave ``transactions``
and ``payout_accounts`` an org beneficiary under XOR CHECKs but left the
``payouts`` ledger user-keyed. This wave mirrors that shape on ``payouts`` so an
org's claimed-payout balance is attributable: ``contributor_id`` is relaxed to
nullable, ``org_id`` is added, and a single-beneficiary XOR CHECK guarantees a
payout belongs to exactly one of a Contributor or an Organization.

Downgrade restores NOT NULL on ``contributor_id`` directly; acceptable on the
dev database because no org payouts (which would hold NULL there) exist before
this wave ships.

Revision ID: 2026_07_05_0065
Revises: 2026_07_04_0064
Create Date: 2026-07-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_05_0065"
down_revision: str | Sequence[str] | None = "2026_07_04_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add org beneficiary column, XOR CHECK, and index on payouts."""
    op.add_column(
        "payouts",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "organizations.id",
                name="fk_payouts_org_id_organizations",
                ondelete="CASCADE",
            ),
            nullable=True,
        ),
    )
    op.alter_column("payouts", "contributor_id", nullable=True)
    op.create_check_constraint(
        "ck_payouts_beneficiary_xor",
        "payouts",
        "(contributor_id IS NULL) != (org_id IS NULL)",
    )
    op.create_index("idx_payouts_org", "payouts", ["org_id"])


def downgrade() -> None:
    """Drop org beneficiary column and restore the contributor NOT NULL."""
    op.drop_index("idx_payouts_org", table_name="payouts")
    op.drop_constraint("ck_payouts_beneficiary_xor", "payouts", type_="check")
    op.alter_column("payouts", "contributor_id", nullable=False)
    op.drop_column("payouts", "org_id")
