"""Create Phase 4b attestation schema foundation.

Revision ID: 2026_06_10_0013
Revises: 2026_06_10_0012
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_10_0013"
down_revision: str | Sequence[str] | None = "2026_06_10_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

attestor_application_status_enum = postgresql.ENUM(
    "pending",
    "approved",
    "rejected",
    "withdrawn",
    name="attestor_application_status_enum",
    create_type=False,
)
attestation_target_enum = postgresql.ENUM(
    "framework",
    "contributor",
    "operator",
    "credential",
    name="attestation_target_enum",
    create_type=False,
)
attestation_status_enum = postgresql.ENUM(
    "pending_fee",
    "matching",
    "offered",
    "accepted",
    "report_submitted",
    "released",
    "disputed",
    "resolved",
    "needs_admin",
    "refunded",
    "closed",
    "cancelled",
    name="attestation_status_enum",
    create_type=False,
)
attestation_outcome_enum = postgresql.ENUM(
    "approved",
    "conditional",
    "rejected",
    name="attestation_outcome_enum",
    create_type=False,
)
attestation_offer_status_enum = postgresql.ENUM(
    "offered",
    "accepted",
    "declined",
    "expired",
    "superseded",
    name="attestation_offer_status_enum",
    create_type=False,
)
attestation_dispute_status_enum = postgresql.ENUM(
    "open",
    "under_review",
    "resolved",
    name="attestation_dispute_status_enum",
    create_type=False,
)
attestation_dispute_resolution_enum = postgresql.ENUM(
    "release",
    "refund",
    "split",
    name="attestation_dispute_resolution_enum",
    create_type=False,
)
attestation_upload_purpose_enum = postgresql.ENUM(
    "report_evidence",
    "credential_evidence",
    name="attestation_upload_purpose_enum",
    create_type=False,
)

ATTESTATION_CONFIG_SEEDS = {
    "attestation_fee_framework": "250.00",
    "attestation_fee_contributor": "300.00",
    "attestation_fee_operator": "300.00",
    "attestation_fee_credential": "100.00",
    "attestation_cohort_size": "3",
    "attestation_completion_sla_days_framework": "7",
    "attestation_completion_sla_days_contributor": "7",
    "attestation_completion_sla_days_operator": "7",
    "attestation_completion_sla_days_credential": "7",
    "attestation_offer_accept_hours": "48",
    "attestation_dispute_window_days": "14",
}


def upgrade() -> None:
    """Apply Phase 4b Slice 1 attestation schema and config defaults."""
    bind = op.get_bind()

    attestor_application_status_enum.create(bind, checkfirst=True)
    attestation_target_enum.create(bind, checkfirst=True)
    attestation_status_enum.create(bind, checkfirst=True)
    attestation_outcome_enum.create(bind, checkfirst=True)
    attestation_offer_status_enum.create(bind, checkfirst=True)
    attestation_dispute_status_enum.create(bind, checkfirst=True)
    attestation_dispute_resolution_enum.create(bind, checkfirst=True)
    attestation_upload_purpose_enum.create(bind, checkfirst=True)

    op.create_table(
        "attestor_applications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            attestor_application_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("specializations", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("jurisdictions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("credentials_summary", sa.Text(), nullable=False),
        sa.Column("sample_work", postgresql.JSONB(), nullable=False),
        sa.Column("professional_references", sa.Text(), nullable=False),
        sa.Column("admin_feedback", sa.Text(), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
    )
    op.create_index(
        "idx_attestor_applications_user_status",
        "attestor_applications",
        ["user_id", "status"],
    )
    op.create_index(
        "uq_attestor_applications_user_pending",
        "attestor_applications",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "attestor_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("specializations", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("jurisdictions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_attestor_profiles_user_id"),
    )
    op.create_index(
        "idx_attestor_profiles_specializations_gin",
        "attestor_profiles",
        ["specializations"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_attestor_profiles_jurisdictions_gin",
        "attestor_profiles",
        ["jurisdictions"],
        postgresql_using="gin",
    )

    op.create_table(
        "credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("issued_date", sa.Date(), nullable=False),
        sa.Column("expires_date", sa.Date(), nullable=True),
        sa.Column(
            "evidence_file_keys",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_credentials_user", "credentials", ["user_id"])

    op.create_table(
        "attestations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("target_type", attestation_target_enum, nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requestor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attestor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            attestation_status_enum,
            nullable=False,
            server_default="pending_fee",
        ),
        sa.Column("outcome", attestation_outcome_enum, nullable=True),
        sa.Column(
            "requested_specializations",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "requested_jurisdictions",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("evidence_references", postgresql.JSONB(), nullable=True),
        sa.Column("report_key", sa.Text(), nullable=True),
        sa.Column("escrow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fee_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispute_window_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("currency = 'USD'", name="ck_attestations_currency_usd"),
        sa.CheckConstraint(
            "fee_amount > 0",
            name="ck_attestations_fee_amount_positive",
        ),
        sa.ForeignKeyConstraint(["requestor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["attestor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["escrow_id"], ["escrows.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "idx_attestations_target",
        "attestations",
        ["target_type", "target_id"],
    )
    op.create_index(
        "idx_attestations_attestor_status",
        "attestations",
        ["attestor_id", "status"],
    )
    op.create_index(
        "idx_attestations_status_dispute_window",
        "attestations",
        ["status", "dispute_window_ends_at"],
    )
    op.create_index(
        "idx_attestations_status_completion_due",
        "attestations",
        ["status", "completion_due_at"],
    )

    op.create_table(
        "attestation_offers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("attestation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attestor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_index", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            attestation_offer_status_enum,
            nullable=False,
            server_default="offered",
        ),
        sa.Column(
            "offered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["attestation_id"],
            ["attestations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["attestor_id"], ["users.id"]),
        sa.UniqueConstraint(
            "attestation_id",
            "attestor_id",
            name="uq_attestation_offers_attestation_attestor",
        ),
    )
    op.create_index(
        "idx_attestation_offers_status_expires_at",
        "attestation_offers",
        ["status", "expires_at"],
    )

    op.create_table(
        "attestation_disputes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("attestation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raised_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            attestation_dispute_status_enum,
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "resolution_type",
            attestation_dispute_resolution_enum,
            nullable=True,
        ),
        sa.Column("release_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("refund_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "resolution_type != 'split' "
            "OR (release_amount IS NOT NULL AND refund_amount IS NOT NULL)",
            name="ck_attestation_disputes_split_has_amounts",
        ),
        sa.ForeignKeyConstraint(
            ["attestation_id"],
            ["attestations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["raised_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"]),
    )
    op.create_index(
        "idx_attestation_disputes_status_created_at",
        "attestation_disputes",
        ["status", "created_at"],
    )

    op.create_table(
        "attestation_upload_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("attestation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", attestation_upload_purpose_enum, nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_limit", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(attestation_id IS NOT NULL AND credential_id IS NULL) "
            "OR (attestation_id IS NULL AND credential_id IS NOT NULL)",
            name="ck_attestation_upload_sessions_single_parent",
        ),
        sa.ForeignKeyConstraint(
            ["attestation_id"],
            ["attestations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credentials.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("s3_key", name="uq_attestation_upload_sessions_s3_key"),
    )
    op.create_index(
        "idx_attestation_upload_sessions_attestation_user_consumed",
        "attestation_upload_sessions",
        ["attestation_id", "user_id", "consumed_at"],
    )
    op.create_index(
        "idx_attestation_upload_sessions_credential_user_consumed",
        "attestation_upload_sessions",
        ["credential_id", "user_id", "consumed_at"],
    )
    op.create_index(
        "idx_attestation_upload_sessions_expires_at",
        "attestation_upload_sessions",
        ["expires_at"],
    )

    for key, value in ATTESTATION_CONFIG_SEEDS.items():
        op.execute(
            sa.text(
                """
                INSERT INTO platform_config (key, value)
                VALUES (:key, :value)
                ON CONFLICT (key) DO NOTHING
                """
            ).bindparams(key=key, value=value)
        )


def downgrade() -> None:
    """Remove Phase 4b Slice 1 attestation schema and config defaults."""
    bind = op.get_bind()

    for key in ATTESTATION_CONFIG_SEEDS:
        op.execute(
            sa.text("DELETE FROM platform_config WHERE key = :key").bindparams(
                key=key
            )
        )

    op.drop_index(
        "idx_attestation_upload_sessions_expires_at",
        table_name="attestation_upload_sessions",
    )
    op.drop_index(
        "idx_attestation_upload_sessions_credential_user_consumed",
        table_name="attestation_upload_sessions",
    )
    op.drop_index(
        "idx_attestation_upload_sessions_attestation_user_consumed",
        table_name="attestation_upload_sessions",
    )
    op.drop_table("attestation_upload_sessions")

    op.drop_index(
        "idx_attestation_disputes_status_created_at",
        table_name="attestation_disputes",
    )
    op.drop_table("attestation_disputes")

    op.drop_index(
        "idx_attestation_offers_status_expires_at",
        table_name="attestation_offers",
    )
    op.drop_table("attestation_offers")

    op.drop_index("idx_attestations_status_completion_due", table_name="attestations")
    op.drop_index("idx_attestations_status_dispute_window", table_name="attestations")
    op.drop_index("idx_attestations_attestor_status", table_name="attestations")
    op.drop_index("idx_attestations_target", table_name="attestations")
    op.drop_table("attestations")

    op.drop_index("idx_credentials_user", table_name="credentials")
    op.drop_table("credentials")

    op.drop_index(
        "idx_attestor_profiles_jurisdictions_gin",
        table_name="attestor_profiles",
    )
    op.drop_index(
        "idx_attestor_profiles_specializations_gin",
        table_name="attestor_profiles",
    )
    op.drop_table("attestor_profiles")

    op.drop_index(
        "uq_attestor_applications_user_pending",
        table_name="attestor_applications",
    )
    op.drop_index(
        "idx_attestor_applications_user_status",
        table_name="attestor_applications",
    )
    op.drop_table("attestor_applications")

    attestation_upload_purpose_enum.drop(bind, checkfirst=True)
    attestation_dispute_resolution_enum.drop(bind, checkfirst=True)
    attestation_dispute_status_enum.drop(bind, checkfirst=True)
    attestation_offer_status_enum.drop(bind, checkfirst=True)
    attestation_outcome_enum.drop(bind, checkfirst=True)
    attestation_status_enum.drop(bind, checkfirst=True)
    attestation_target_enum.drop(bind, checkfirst=True)
    attestor_application_status_enum.drop(bind, checkfirst=True)
