"""Drop the retired individual-attestor tables and columns.

Final retirement migration for the Organizations-as-Attestors sub-project
(docs/superpowers/plans/2026-07-04-org-attestor.md, Task 13). Every code path
that read or wrote these structures was removed across the sliced-purge commits
that precede this migration; a repository grep confirms zero remaining
references before the drop.

Dropped:
    * columns ``attestations.attestor_id`` (+ index
      ``idx_attestations_attestor_status``) and ``attestation_offers.attestor_id``
      (+ unique ``uq_attestation_offers_attestation_attestor``),
    * column ``attestor_trials.application_id`` (+ index
      ``idx_attestor_trials_application``) — the legacy individual-application
      key; org trials key on ``org_application_id``. (The plan text named
      ``attestor_trials.user_id``, but the table has always keyed on
      ``application_id``; see migration 2026_07_04_0064's note.)
    * column ``attestation_upload_sessions.application_id`` (+ index
      ``idx_attestation_upload_sessions_application_user_consumed``), the third
      legacy upload parent (individual attestor-application document uploads);
      its single-parent XOR check is relaxed to attestation-or-credential.
    * tables ``attestor_profiles`` and ``attestor_applications``,
    * PG enum type ``attestor_application_status_enum`` (used only by
      ``attestor_applications``). ``tax_document_type_enum`` is NOT dropped: it
      is shared with the org attestor application table.

IRREVERSIBLE DATA LOSS: the downgrade recreates the dropped tables, columns,
indexes, constraints, and enum type as empty schema for structural
reversibility only. Any row data that existed in the dropped structures is
permanently lost and is not restored on downgrade.

Revision ID: 2026_07_06_0068
Revises: 2026_07_05_0067
Create Date: 2026-07-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_06_0068"
down_revision: str | Sequence[str] | None = "2026_07_05_0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPLICATION_STATUS_VALUES = (
    "pending",
    "approved",
    "rejected",
    "withdrawn",
    "submitted",
    "identity_verified",
    "professional_verified",
    "expert_verified",
    "active",
    "held",
)


def upgrade() -> None:
    """Drop the retired individual-attestor structures (irreversible data loss)."""
    # Legacy assignee / offer keys on the retained tables.
    op.drop_constraint(
        "uq_attestation_offers_attestation_attestor",
        "attestation_offers",
        type_="unique",
    )
    op.drop_index("idx_attestations_attestor_status", table_name="attestations")
    op.drop_index("idx_attestor_trials_application", table_name="attestor_trials")
    op.drop_column("attestations", "attestor_id")
    op.drop_column("attestation_offers", "attestor_id")
    # Legacy individual-application key; FK to attestor_applications is dropped
    # with the column so the table drop below succeeds.
    op.drop_column("attestor_trials", "application_id")

    # Upload sessions carried a third legacy parent (individual attestor
    # application document uploads); drop it and relax the single-parent XOR
    # check to attestation-or-credential so attestor_applications can be dropped.
    op.drop_index(
        "idx_attestation_upload_sessions_application_user_consumed",
        table_name="attestation_upload_sessions",
    )
    op.drop_constraint(
        "ck_attestation_upload_sessions_single_parent",
        "attestation_upload_sessions",
        type_="check",
    )
    # Orphaned individual attestor-application upload sessions would violate the
    # relaxed attestation-or-credential check once application_id is gone.
    op.execute(
        "DELETE FROM attestation_upload_sessions WHERE application_id IS NOT NULL"
    )
    op.drop_column("attestation_upload_sessions", "application_id")
    op.create_check_constraint(
        "ck_attestation_upload_sessions_single_parent",
        "attestation_upload_sessions",
        "(attestation_id IS NOT NULL AND credential_id IS NULL) "
        "OR (attestation_id IS NULL AND credential_id IS NOT NULL)",
    )

    # Retired individual-attestor tables.
    op.drop_table("attestor_profiles")
    op.drop_table("attestor_applications")

    # Enum type used only by the dropped attestor_applications table.
    # tax_document_type_enum is intentionally left in place (shared with the org
    # attestor application table).
    postgresql.ENUM(name="attestor_application_status_enum").drop(
        op.get_bind(), checkfirst=True
    )


def downgrade() -> None:
    """Recreate the dropped structures as empty schema (no data is restored)."""
    application_status = postgresql.ENUM(
        *_APPLICATION_STATUS_VALUES,
        name="attestor_application_status_enum",
    )
    application_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "attestor_applications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                *_APPLICATION_STATUS_VALUES,
                name="attestor_application_status_enum",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("specializations", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("jurisdictions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("credentials_summary", sa.Text(), nullable=False),
        sa.Column("sample_work", postgresql.JSONB(), nullable=False),
        sa.Column("professional_references", sa.Text(), nullable=False),
        sa.Column("admin_feedback", sa.Text(), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legal_name", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column(
            "professional_body_numbers",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("cv_file_key", sa.Text(), nullable=True),
        sa.Column(
            "coi_declarations",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("coi_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confidentiality_signed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("coi_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sectors",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "framework_categories",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "needs_retag",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("kyc_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kyc_name_match", sa.Boolean(), nullable=True),
        sa.Column(
            "tax_document_type",
            postgresql.ENUM(name="tax_document_type_enum", create_type=False),
            nullable=True,
        ),
        sa.Column("tax_document_key", sa.Text(), nullable=True),
        sa.Column("payout_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["payout_account_id"], ["payout_accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_attestor_applications_user_status",
        "attestor_applications",
        ["user_id", "status"],
    )
    op.create_index(
        "uq_attestor_applications_user_submitted",
        "attestor_applications",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'submitted'"),
    )

    # Restore the upload-session legacy application parent + 3-way XOR check.
    op.drop_constraint(
        "ck_attestation_upload_sessions_single_parent",
        "attestation_upload_sessions",
        type_="check",
    )
    op.add_column(
        "attestation_upload_sessions",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "attestation_upload_sessions_application_id_fkey",
        "attestation_upload_sessions",
        "attestor_applications",
        ["application_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "idx_attestation_upload_sessions_application_user_consumed",
        "attestation_upload_sessions",
        ["application_id", "user_id", "consumed_at"],
    )
    op.create_check_constraint(
        "ck_attestation_upload_sessions_single_parent",
        "attestation_upload_sessions",
        "(attestation_id IS NOT NULL AND credential_id IS NULL "
        "AND application_id IS NULL) "
        "OR (attestation_id IS NULL AND credential_id IS NOT NULL "
        "AND application_id IS NULL) "
        "OR (attestation_id IS NULL AND credential_id IS NULL "
        "AND application_id IS NOT NULL)",
    )

    op.create_table(
        "attestor_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("specializations", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("jurisdictions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "verification_level",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "sectors",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "framework_categories",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "coi_declarations",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("coi_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confidentiality_signed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("coi_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coi_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "late_submission_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("suspension_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certified_attestor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
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
    # The sectors/categories GIN indexes (migration 0041) exist at 0067 even
    # though the retired ORM model no longer listed them; recreate both so the
    # full-history downgrade chain that drops them by name still applies.
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

    # Legacy individual-application key on attestor_trials.
    op.add_column(
        "attestor_trials",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "attestor_trials_application_id_fkey",
        "attestor_trials",
        "attestor_applications",
        ["application_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "idx_attestor_trials_application",
        "attestor_trials",
        ["application_id"],
    )

    # Legacy assignee columns on the retained attestation tables.
    op.add_column(
        "attestations",
        sa.Column("attestor_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "attestations_attestor_id_fkey",
        "attestations",
        "users",
        ["attestor_id"],
        ["id"],
    )
    op.create_index(
        "idx_attestations_attestor_status",
        "attestations",
        ["attestor_id", "status"],
    )
    op.add_column(
        "attestation_offers",
        sa.Column("attestor_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "attestation_offers_attestor_id_fkey",
        "attestation_offers",
        "users",
        ["attestor_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_attestation_offers_attestation_attestor",
        "attestation_offers",
        ["attestation_id", "attestor_id"],
    )
