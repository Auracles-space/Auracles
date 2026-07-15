"""Calibration trial schema: fixtures, answer keys, and nominee scores.

Supports the Org Attestor calibration trial. Adds calibration-fixture flags
to frameworks, grading fields plus the submitted status to attestor trials,
and the per-fixture answer-key / per-trial score tables.

Revision ID: 2026_07_15_0084
Revises: 2026_07_14_0083
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_15_0084"
down_revision: str | Sequence[str] | None = "2026_07_14_0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add calibration-fixture flags and trial grading schema."""
    op.execute(
        "ALTER TYPE attestor_trial_status_enum ADD VALUE IF NOT EXISTS 'submitted'"
    )

    op.add_column(
        "frameworks",
        sa.Column(
            "is_calibration",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "frameworks",
        sa.Column("calibration_review_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "attestor_trials",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attestor_trials",
        sa.Column("score_pct", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "attestor_trials",
        sa.Column("auto_result", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_attestor_trials_auto_result",
        "attestor_trials",
        "auto_result IS NULL OR auto_result IN ('pass','fail')",
    )

    op.create_table(
        "attestor_trial_answer_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "framework_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("frameworks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dimension_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestation_rubric_dimensions.id"),
            nullable=False,
        ),
        sa.Column("expected_score", sa.Integer(), nullable=False),
        sa.Column(
            "tolerance",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.UniqueConstraint(
            "framework_id",
            "dimension_id",
            name="uq_attestor_trial_answer_keys_framework_dimension",
        ),
        sa.CheckConstraint(
            "expected_score BETWEEN 1 AND 5",
            name="ck_attestor_trial_answer_keys_score_range",
        ),
        sa.CheckConstraint(
            "tolerance BETWEEN 0 AND 4",
            name="ck_attestor_trial_answer_keys_tolerance_range",
        ),
    )

    op.create_table(
        "attestor_trial_rubric_scores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "trial_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestor_trials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dimension_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestation_rubric_dimensions.id"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "trial_id",
            "dimension_id",
            name="uq_attestor_trial_rubric_scores_trial_dimension",
        ),
        sa.CheckConstraint(
            "score BETWEEN 1 AND 5",
            name="ck_attestor_trial_rubric_scores_range",
        ),
    )


def downgrade() -> None:
    """Drop trial tables and additive columns, leaving the enum label in place."""
    op.execute(
        "UPDATE attestor_trials SET status = 'assigned' WHERE status = 'submitted'"
    )
    op.drop_table("attestor_trial_rubric_scores")
    op.drop_table("attestor_trial_answer_keys")
    op.drop_constraint(
        "ck_attestor_trials_auto_result",
        "attestor_trials",
        type_="check",
    )
    op.drop_column("attestor_trials", "auto_result")
    op.drop_column("attestor_trials", "score_pct")
    op.drop_column("attestor_trials", "submitted_at")
    op.drop_column("frameworks", "calibration_review_type")
    op.drop_column("frameworks", "is_calibration")
