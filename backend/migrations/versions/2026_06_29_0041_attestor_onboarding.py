"""Add Attestor onboarding gates: levels, CoI, taxonomy, credential cross-check, trials.

Supports Module 1 (Attestor Onboarding). Extends attestor_applications into a
gated state machine, adds verification levels + taxonomy + CoI to profiles,
adds manual registry cross-check fields to credentials, and a stubbed
attestor_trials table for calibration.

Revision ID: 2026_06_29_0041
Revises: 2026_06_28_0040
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_29_0041"
down_revision: str | Sequence[str] | None = "2026_06_28_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_APP_STATUSES = (
    "submitted",
    "identity_verified",
    "professional_verified",
    "expert_verified",
    "active",
    "held",
)


def upgrade() -> None:
    """Add onboarding columns, new enums, and the attestor_trials table."""
    # 1. Extend the application status enum (ADD VALUE needs autocommit).
    with op.get_context().autocommit_block():
        for value in _NEW_APP_STATUSES:
            op.execute(
                "ALTER TYPE attestor_application_status_enum "
                f"ADD VALUE IF NOT EXISTS '{value}'"
            )

    # 2. New enums. create_type=False below: we create these explicitly via
    # .create() on the next lines, so add_column/create_table must not try to
    # create them again (the same Python object is reused as each column's
    # type so SQLAlchemy's dialect-level "already created" cache applies).
    trial_status = postgresql.ENUM(
        "assigned",
        "passed",
        "failed",
        name="attestor_trial_status_enum",
        create_type=False,
    )
    body = postgresql.ENUM(
        "cfa_institute",
        "aicpa",
        "isaca",
        "rics",
        "sra",
        "state_bar",
        "fca",
        "acams",
        "other",
        name="attestor_credential_body_enum",
        create_type=False,
    )
    tax_type = postgresql.ENUM(
        "w9", "w8ben", "other", name="tax_document_type_enum", create_type=False
    )
    bind = op.get_bind()
    trial_status.create(bind, checkfirst=True)
    body.create(bind, checkfirst=True)
    tax_type.create(bind, checkfirst=True)

    # 3. attestor_applications new columns.
    op.add_column(
        "attestor_applications", sa.Column("legal_name", sa.Text(), nullable=True)
    )
    op.add_column(
        "attestor_applications", sa.Column("linkedin_url", sa.Text(), nullable=True)
    )
    op.add_column(
        "attestor_applications",
        sa.Column(
            "professional_body_numbers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "attestor_applications", sa.Column("cv_file_key", sa.Text(), nullable=True)
    )
    op.add_column(
        "attestor_applications",
        sa.Column(
            "coi_declarations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "attestor_applications",
        sa.Column("coi_signed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attestor_applications",
        sa.Column("coi_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attestor_applications",
        sa.Column(
            "sectors",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "attestor_applications",
        sa.Column(
            "framework_categories",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "attestor_applications",
        sa.Column(
            "needs_retag", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "attestor_applications",
        sa.Column("kyc_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attestor_applications",
        sa.Column("kyc_name_match", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "attestor_applications", sa.Column("tax_document_type", tax_type, nullable=True)
    )
    op.add_column(
        "attestor_applications", sa.Column("tax_document_key", sa.Text(), nullable=True)
    )
    op.add_column(
        "attestor_applications",
        sa.Column(
            "payout_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payout_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # 4. Data migration: map legacy statuses + seed sectors from specializations.
    op.execute(
        "UPDATE attestor_applications SET status='submitted' WHERE status='pending'"
    )
    op.execute(
        "UPDATE attestor_applications SET status='active' WHERE status='approved'"
    )
    op.execute(
        "UPDATE attestor_applications SET sectors=specializations, needs_retag=true "
        "WHERE array_length(specializations, 1) IS NOT NULL"
    )

    # 5. attestor_profiles new columns.
    op.add_column(
        "attestor_profiles",
        sa.Column(
            "verification_level",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "attestor_profiles",
        sa.Column(
            "sectors",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "attestor_profiles",
        sa.Column(
            "framework_categories",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "attestor_profiles",
        sa.Column(
            "coi_declarations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "attestor_profiles",
        sa.Column("coi_signed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attestor_profiles",
        sa.Column("coi_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE attestor_profiles SET sectors=specializations "
        "WHERE array_length(specializations, 1) IS NOT NULL"
    )
    op.create_index(
        "idx_attestor_profiles_sectors_gin",
        "attestor_profiles",
        ["sectors"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_attestor_profiles_categories_gin",
        "attestor_profiles",
        ["framework_categories"],
        postgresql_using="gin",
    )

    # 6. credentials cross-check columns.
    op.add_column("credentials", sa.Column("issuing_body", body, nullable=True))
    op.add_column(
        "credentials", sa.Column("good_standing", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "credentials",
        sa.Column("registry_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "credentials",
        sa.Column(
            "registry_checked_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "credentials", sa.Column("registry_reference", sa.Text(), nullable=True)
    )

    # 7. attestor_trials table.
    op.create_table(
        "attestor_trials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestor_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "seeded_framework_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("frameworks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", trial_status, nullable=False, server_default="assigned"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "attempt >= 1 AND attempt <= 2", name="ck_attestor_trials_attempt_range"
        ),
    )
    op.create_index(
        "idx_attestor_trials_application", "attestor_trials", ["application_id"]
    )


def downgrade() -> None:
    """Drop onboarding columns, indexes, trials table, and new enums.

    Enum *values* added to attestor_application_status_enum are not removed
    (Postgres cannot drop enum values); this is acceptable and non-breaking.
    """
    op.drop_index("idx_attestor_trials_application", table_name="attestor_trials")
    op.drop_table("attestor_trials")
    for col in (
        "registry_reference",
        "registry_checked_by",
        "registry_checked_at",
        "good_standing",
        "issuing_body",
    ):
        op.drop_column("credentials", col)
    op.drop_index(
        "idx_attestor_profiles_categories_gin", table_name="attestor_profiles"
    )
    op.drop_index("idx_attestor_profiles_sectors_gin", table_name="attestor_profiles")
    for col in (
        "coi_expires_at",
        "coi_signed_at",
        "coi_declarations",
        "framework_categories",
        "sectors",
        "verification_level",
    ):
        op.drop_column("attestor_profiles", col)
    for col in (
        "payout_account_id",
        "tax_document_key",
        "tax_document_type",
        "kyc_name_match",
        "kyc_verified_at",
        "needs_retag",
        "framework_categories",
        "sectors",
        "coi_expires_at",
        "coi_signed_at",
        "coi_declarations",
        "cv_file_key",
        "professional_body_numbers",
        "linkedin_url",
        "legal_name",
    ):
        op.drop_column("attestor_applications", col)
    bind = op.get_bind()
    for name in (
        "attestor_trial_status_enum",
        "attestor_credential_body_enum",
        "tax_document_type_enum",
    ):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
