"""Create reputation_scores table and seed reputation platform configuration.

Supports Phase 5e Slice 1 by adding durable per-subject reputation snapshots
and the seeded tuning knobs the scoring engine will load in later slices.

Revision ID: 2026_06_13_0025
Revises: 2026_06_12_0024
Create Date: 2026-06-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_13_0025"
down_revision: str | Sequence[str] | None = "2026_06_12_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REPUTATION_SEEDS = {
    "reputation_weights_framework": (
        '{"reviews":0.35,"attestations":0.30,"adoption":0.35,'
        '"completion":0.00,"recency":0.00}'
    ),
    "reputation_weights_contributor": (
        '{"verification":0.15,"framework_performance":0.30,'
        '"reviews_received":0.20,"attestations_received":0.20,"activity":0.15}'
    ),
    "reputation_weights_operator": (
        '{"purchase_activity":0.40,"license_compliance":0.25,'
        '"review_quality":0.20,"engagement":0.15}'
    ),
    "reputation_min_activity_framework": "3",
    "reputation_min_activity_contributor": "1",
    "reputation_min_activity_operator": "1",
    "reputation_prior": "0.5",
    "reputation_prior_strength_k": "5",
    "reputation_decay_halflife_days": "180",
    "reputation_dispute_penalty": "0.20",
}


def upgrade() -> None:
    """Create the reputation score table and seed reputation config defaults."""
    op.create_table(
        "reputation_scores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "components",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_provisional",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("last_calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("subject_type", "subject_id", name="uq_reputation_subject"),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="ck_reputation_score_range",
        ),
        sa.CheckConstraint(
            "subject_type IN ('framework','contributor','operator')",
            name="ck_reputation_subject_type",
        ),
    )
    op.create_index(
        "ix_reputation_subject_type_score",
        "reputation_scores",
        ["subject_type", "score"],
    )
    for key, value in _REPUTATION_SEEDS.items():
        op.execute(
            sa.text(
                "INSERT INTO platform_config (key, value) VALUES (:key, :value) "
                "ON CONFLICT (key) DO NOTHING"
            ).bindparams(key=key, value=value)
        )


def downgrade() -> None:
    """Drop the reputation score table and seeded reputation config defaults."""
    op.execute(
        sa.text("DELETE FROM platform_config WHERE key IN :keys").bindparams(
            sa.bindparam("keys", tuple(_REPUTATION_SEEDS), expanding=True)
        )
    )
    op.drop_index("ix_reputation_subject_type_score", table_name="reputation_scores")
    op.drop_table("reputation_scores")
