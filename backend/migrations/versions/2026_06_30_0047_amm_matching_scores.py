"""Add AMM match-score columns and CoI reminder timestamp.

Supports Attestation Module 3 (AMM Matching Engine). Persists the computed
match score and factor breakdown on each cohort offer for auditability, and
adds a CoI reminder timestamp to Attestor profiles so the daily reminder task
can deduplicate sends across a signing cycle.

Maps to: spec 2026-06-30-attestation-module-3-amm-matching-design.md §5, §7.

Revision ID: 2026_06_30_0047
Revises: 2026_06_30_0046
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_30_0047"
down_revision: str | Sequence[str] | None = "2026_06_30_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.add_column(
        "attestation_offers",
        sa.Column("match_score", sa.Numeric(4, 3), nullable=True),
    )
    op.add_column(
        "attestation_offers",
        sa.Column(
            "score_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "attestor_profiles",
        sa.Column(
            "coi_reminder_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Rollback the migration."""
    op.drop_column("attestor_profiles", "coi_reminder_sent_at")
    op.drop_column("attestation_offers", "score_breakdown")
    op.drop_column("attestation_offers", "match_score")
