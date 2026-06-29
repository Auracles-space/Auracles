"""Add Attestor tax-document upload purpose and application parent linkage.

Supports Module 1 (Attestor Onboarding) tax-document upload sessions by
adding the `attestor_tax_document` upload purpose and allowing upload
sessions to attach directly to an Attestor application.

Revision ID: 2026_06_29_0042
Revises: 2026_06_29_0041
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_29_0042"
down_revision: str | Sequence[str] | None = "2026_06_29_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the tax-document upload purpose and application upload parent."""
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE attestation_upload_purpose_enum "
            "ADD VALUE IF NOT EXISTS 'attestor_tax_document'"
        )

    op.add_column(
        "attestation_upload_sessions",
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestor_applications.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.drop_constraint(
        "ck_attestation_upload_sessions_single_parent",
        "attestation_upload_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_attestation_upload_sessions_single_parent",
        "attestation_upload_sessions",
        "(attestation_id IS NOT NULL "
        "AND credential_id IS NULL "
        "AND application_id IS NULL) "
        "OR (attestation_id IS NULL "
        "AND credential_id IS NOT NULL "
        "AND application_id IS NULL) "
        "OR (attestation_id IS NULL "
        "AND credential_id IS NULL "
        "AND application_id IS NOT NULL)",
    )
    op.create_index(
        "idx_attestation_upload_sessions_application_user_consumed",
        "attestation_upload_sessions",
        ["application_id", "user_id", "consumed_at"],
    )


def downgrade() -> None:
    """Restore the two-parent upload-session constraint.

    The `attestor_tax_document` enum value is intentionally left in place
    because Postgres cannot drop a single enum value cleanly; the orphan value
    is harmless.
    """
    op.drop_index(
        "idx_attestation_upload_sessions_application_user_consumed",
        table_name="attestation_upload_sessions",
    )
    op.drop_constraint(
        "ck_attestation_upload_sessions_single_parent",
        "attestation_upload_sessions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_attestation_upload_sessions_single_parent",
        "attestation_upload_sessions",
        "(attestation_id IS NOT NULL AND credential_id IS NULL)"
        " OR (attestation_id IS NULL AND credential_id IS NOT NULL)",
    )
    op.drop_column("attestation_upload_sessions", "application_id")
