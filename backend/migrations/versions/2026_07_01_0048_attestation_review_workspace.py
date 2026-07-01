"""Add the Module 4 review-workspace schema and seed review rubrics.

Introduces the in_review working status, rubric/annotation/clarification
tables, report workspace columns, and the attestor late-submission counter.
Seeds all four review-type rubrics (version 1) plus canned methodology text.

Maps to: design spec section 3 and workflow sections 4.2 and 4.6.

Revision ID: 2026_07_01_0048
Revises: 2026_06_30_0047
Create Date: 2026-07-01
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.modules.attestation import rubrics

revision: str = "2026_07_01_0048"
down_revision: str | Sequence[str] | None = "2026_06_30_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANNOTATION_TYPE_ENUM = postgresql.ENUM(
    "endorsement",
    "concern",
    "jurisdictional_caveat",
    "revision_recommended",
    name="attestation_annotation_type_enum",
    create_type=False,
)
CLARIFICATION_STATUS_ENUM = postgresql.ENUM(
    "open",
    "answered",
    "expired",
    name="attestation_clarification_status_enum",
    create_type=False,
)
REVIEW_TYPE_ENUM = postgresql.ENUM(
    name="attestation_review_type_enum",
    create_type=False,
)


def upgrade() -> None:
    """Apply the review-workspace schema and rubric seed."""
    bind = op.get_bind()

    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE attestation_status_enum "
            "ADD VALUE IF NOT EXISTS 'in_review' AFTER 'accepted'"
        )

    ANNOTATION_TYPE_ENUM.create(bind, checkfirst=True)
    CLARIFICATION_STATUS_ENUM.create(bind, checkfirst=True)

    op.add_column(
        "attestations",
        sa.Column("review_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attestations",
        sa.Column("rubric_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "attestations",
        sa.Column("conditions", sa.Text(), nullable=True),
    )
    op.add_column(
        "attestations",
        sa.Column(
            "submitted_late",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "attestor_profiles",
        sa.Column(
            "late_submission_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.create_table(
        "attestation_rubric_dimensions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("review_type", REVIEW_TYPE_ENUM, nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(4, 3), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint(
            "review_type",
            "version",
            "key",
            name="uq_attestation_rubric_dimensions_type_version_key",
        ),
    )
    op.create_index(
        "idx_attestation_rubric_dimensions_type_version_order",
        "attestation_rubric_dimensions",
        ["review_type", "version", "display_order"],
    )

    op.create_table(
        "attestation_rubric_methodology",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("review_type", REVIEW_TYPE_ENUM, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "review_type",
            "version",
            name="uq_attestation_rubric_methodology_type_version",
        ),
    )

    op.create_table(
        "attestation_rubric_scores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "attestation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dimension_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestation_rubric_dimensions.id"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=True),
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
            "attestation_id",
            "dimension_id",
            name="uq_attestation_rubric_scores_attestation_dimension",
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score BETWEEN 1 AND 5)",
            name="ck_attestation_rubric_scores_range",
        ),
    )

    op.create_table(
        "attestation_annotations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "attestation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artifacts.id"),
            nullable=True,
        ),
        sa.Column("location_label", sa.Text(), nullable=False),
        sa.Column("quoted_excerpt", sa.Text(), nullable=True),
        sa.Column("annotation_type", ANNOTATION_TYPE_ENUM, nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
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
    )
    op.create_index(
        "idx_attestation_annotations_attestation",
        "attestation_annotations",
        ["attestation_id"],
    )

    op.create_table(
        "attestation_clarifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "attestation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("response_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            CLARIFICATION_STATUS_ENUM,
            nullable=False,
            server_default="open",
        ),
    )
    op.create_index(
        "idx_attestation_clarifications_status_due",
        "attestation_clarifications",
        ["status", "response_due_at"],
    )
    op.create_index(
        "idx_attestation_clarifications_attestation",
        "attestation_clarifications",
        ["attestation_id"],
    )

    op.bulk_insert(
        sa.table(
            "attestation_rubric_dimensions",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("review_type", REVIEW_TYPE_ENUM),
            sa.column("key", sa.Text()),
            sa.column("label", sa.Text()),
            sa.column("weight", sa.Numeric(4, 3)),
            sa.column("display_order", sa.Integer()),
            sa.column("version", sa.Integer()),
        ),
        [
            {
                "id": uuid.uuid4(),
                "review_type": review_type,
                "key": dimension.key,
                "label": dimension.label,
                "weight": dimension.weight,
                "display_order": dimension.display_order,
                "version": rubrics.RUBRIC_VERSION,
            }
            for review_type, dimensions in rubrics.RUBRICS.items()
            for dimension in dimensions
        ],
    )
    op.bulk_insert(
        sa.table(
            "attestation_rubric_methodology",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("review_type", REVIEW_TYPE_ENUM),
            sa.column("version", sa.Integer()),
            sa.column("text_body", sa.Text()),
        ),
        [
            {
                "id": uuid.uuid4(),
                "review_type": review_type,
                "version": rubrics.RUBRIC_VERSION,
                "text_body": text_body,
            }
            for review_type, text_body in rubrics.METHODOLOGY.items()
        ],
    )


def downgrade() -> None:
    """Remove the review-workspace schema; the enum value remains in place."""
    op.drop_index(
        "idx_attestation_clarifications_attestation",
        table_name="attestation_clarifications",
    )
    op.drop_index(
        "idx_attestation_clarifications_status_due",
        table_name="attestation_clarifications",
    )
    op.drop_table("attestation_clarifications")

    op.drop_index(
        "idx_attestation_annotations_attestation",
        table_name="attestation_annotations",
    )
    op.drop_table("attestation_annotations")

    op.drop_table("attestation_rubric_scores")
    op.drop_table("attestation_rubric_methodology")

    op.drop_index(
        "idx_attestation_rubric_dimensions_type_version_order",
        table_name="attestation_rubric_dimensions",
    )
    op.drop_table("attestation_rubric_dimensions")

    op.drop_column("attestor_profiles", "late_submission_count")
    op.drop_column("attestations", "submitted_late")
    op.drop_column("attestations", "conditions")
    op.drop_column("attestations", "rubric_version")
    op.drop_column("attestations", "review_started_at")

    bind = op.get_bind()
    ANNOTATION_TYPE_ENUM.drop(bind, checkfirst=True)
    CLARIFICATION_STATUS_ENUM.drop(bind, checkfirst=True)
