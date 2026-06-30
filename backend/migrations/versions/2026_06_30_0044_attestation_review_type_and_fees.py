"""Add attestation review_type + brief, review-tier fees, and 10-day SLA.

Implements Module 2a (workflow-doc section 2.1 through 2.4): an orthogonal
review-type dimension and structured brief on attestation requests, review-tier
framework fees, and the 10-day SLA value. Additive and backward-compatible;
review_type and brief stay nullable so interim rows survive.

Revision ID: 2026_06_30_0044
Revises: 2026_06_29_0043
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_30_0044"
down_revision: str | Sequence[str] | None = "2026_06_29_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVIEW_TYPE_ENUM = postgresql.ENUM(
    "quality",
    "compliance",
    "expert",
    "provenance",
    name="attestation_review_type_enum",
)

REVIEW_FEE_SEEDS = {
    "attestation_fee_review_quality": "500.00",
    "attestation_fee_review_compliance": "1200.00",
    "attestation_fee_review_expert": "2500.00",
    "attestation_fee_review_provenance": "500.00",
}

SLA_KEYS = (
    "attestation_completion_sla_days_framework",
    "attestation_completion_sla_days_contributor",
    "attestation_completion_sla_days_operator",
    "attestation_completion_sla_days_credential",
)


def upgrade() -> None:
    """Create the review-type enum, columns, fees, and 10-day SLA."""
    bind = op.get_bind()
    REVIEW_TYPE_ENUM.create(bind, checkfirst=True)
    op.add_column(
        "attestations",
        sa.Column(
            "review_type",
            postgresql.ENUM(name="attestation_review_type_enum", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "attestations",
        sa.Column("brief", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    for key, value in REVIEW_FEE_SEEDS.items():
        op.execute(
            sa.text(
                """
                INSERT INTO platform_config (key, value)
                VALUES (:key, :value)
                ON CONFLICT (key) DO NOTHING
                """
            ).bindparams(key=key, value=value)
        )
    sla_update = sa.text("UPDATE platform_config SET value = '10' WHERE key = :key")
    for key in SLA_KEYS:
        op.execute(sla_update.bindparams(key=key))


def downgrade() -> None:
    """Drop the review-type columns/enum, remove fees, restore 7-day SLA."""
    bind = op.get_bind()
    sla_revert = sa.text("UPDATE platform_config SET value = '7' WHERE key = :key")
    for key in SLA_KEYS:
        op.execute(sla_revert.bindparams(key=key))
    fee_delete = sa.text("DELETE FROM platform_config WHERE key = :key")
    for key in REVIEW_FEE_SEEDS:
        op.execute(fee_delete.bindparams(key=key))
    op.drop_column("attestations", "brief")
    op.drop_column("attestations", "review_type")
    REVIEW_TYPE_ENUM.drop(bind, checkfirst=True)
