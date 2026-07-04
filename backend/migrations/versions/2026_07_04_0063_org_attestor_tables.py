"""Org attestor tables: application, profile, member NDA (wave 1).

First migration wave of the Organizations-as-Attestors sub-project
(docs/superpowers/specs/2026-07-04-org-attestor-design.md, data-model
section): org_attestor_applications carries the 8-gate vetting state,
org_attestor_profiles is the AMM matching identity that replaces
attestor_profiles, and org_member_ndas records per-member NDA
signatures required before a member may be staffed on attestations.
Purely additive; individual attestor structures are dropped only in
the final reviewed migration.

Revision ID: 2026_07_04_0063
Revises: 2026_07_03_0062
Create Date: 2026-07-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_04_0063"
down_revision: str | Sequence[str] | None = "2026_07_03_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORG_ATTESTOR_APPLICATION_STATUS = postgresql.ENUM(
    "draft",
    "submitted",
    "needs_info",
    "approved",
    "rejected",
    name="org_attestor_application_status_enum",
    create_type=False,
)
# Existing type from the individual attestor migrations; reused, never dropped here.
TAX_DOCUMENT_TYPE = postgresql.ENUM(
    "w9",
    "w8ben",
    "other",
    name="tax_document_type_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create org attestor application, profile, and member NDA tables."""
    bind = op.get_bind()
    ORG_ATTESTOR_APPLICATION_STATUS.create(bind, checkfirst=True)

    op.create_table(
        "org_attestor_applications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            ORG_ATTESTOR_APPLICATION_STATUS,
            nullable=False,
            server_default="draft",
        ),
        sa.Column("legal_name", sa.Text(), nullable=True),
        sa.Column("registration_number", sa.Text(), nullable=True),
        sa.Column(
            "incorporation_doc_keys",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("kyb_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "kyb_verified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("specializations", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("jurisdictions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "sectors",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "framework_categories",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("credentials_summary", sa.Text(), nullable=False),
        sa.Column("sample_work", postgresql.JSONB(), nullable=False),
        sa.Column("professional_references", sa.Text(), nullable=False),
        sa.Column(
            "coi_declarations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("coi_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coi_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confidentiality_signed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "payout_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payout_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tax_document_type", TAX_DOCUMENT_TYPE, nullable=True),
        sa.Column("tax_document_key", sa.Text(), nullable=True),
        sa.Column(
            "trial_attestation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "trial_member_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org_members.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("admin_feedback", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "uq_org_attestor_app_live",
        "org_attestor_applications",
        ["org_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('draft', 'submitted', 'needs_info')"),
    )

    op.create_table(
        "org_attestor_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("specializations", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("jurisdictions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "sectors",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "framework_categories",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "verification_level",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "coi_declarations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("coi_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coi_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coi_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confidentiality_signed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "late_submission_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("suspension_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certified_attestor_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "idx_org_attestor_profiles_specializations_gin",
        "org_attestor_profiles",
        ["specializations"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_org_attestor_profiles_jurisdictions_gin",
        "org_attestor_profiles",
        ["jurisdictions"],
        postgresql_using="gin",
    )

    op.create_table(
        "org_member_ndas",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "member_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org_members.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("nda_version", sa.Text(), nullable=False),
        sa.Column(
            "signed_at",
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
    )


def downgrade() -> None:
    """Drop org attestor tables and the application status enum."""
    op.drop_table("org_member_ndas")
    op.drop_index(
        "idx_org_attestor_profiles_jurisdictions_gin",
        table_name="org_attestor_profiles",
    )
    op.drop_index(
        "idx_org_attestor_profiles_specializations_gin",
        table_name="org_attestor_profiles",
    )
    op.drop_table("org_attestor_profiles")
    op.drop_index("uq_org_attestor_app_live", table_name="org_attestor_applications")
    op.drop_table("org_attestor_applications")
    bind = op.get_bind()
    ORG_ATTESTOR_APPLICATION_STATUS.drop(bind, checkfirst=True)
    # tax_document_type_enum is owned by the individual attestor migration; kept.
