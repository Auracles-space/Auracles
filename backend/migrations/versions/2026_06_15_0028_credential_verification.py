"""Add manual verification fields to credentials.

Supports the credential-verification feature: a manual, Admin-driven
unverified->pending->verified|rejected lifecycle plus issuer metadata used by
reviewers. Maps to FR-ATT-003 / FR-SET-002 and the full-spec Credential Registry.

Revision ID: 2026_06_15_0028
Revises: 2026_06_13_0027
Create Date: 2026-06-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_15_0028"
down_revision: str | Sequence[str] | None = "2026_06_13_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_ENUM = postgresql.ENUM(
    "unverified",
    "pending",
    "verified",
    "rejected",
    name="credential_verification_status_enum",
    create_type=False,
)
_ISSUER_TYPE_ENUM = postgresql.ENUM(
    "institution",
    "organisation",
    "government",
    "association",
    name="credential_issuer_type_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create verification enums and add columns to credentials."""
    bind = op.get_bind()
    _STATUS_ENUM.create(bind, checkfirst=True)
    _ISSUER_TYPE_ENUM.create(bind, checkfirst=True)
    op.add_column(
        "credentials",
        sa.Column(
            "verification_status",
            _STATUS_ENUM,
            nullable=False,
            server_default="unverified",
        ),
    )
    op.add_column(
        "credentials", sa.Column("credential_type", sa.Text(), nullable=True)
    )
    op.add_column(
        "credentials", sa.Column("verification_url", sa.Text(), nullable=True)
    )
    op.add_column(
        "credentials", sa.Column("reference_number", sa.Text(), nullable=True)
    )
    op.add_column(
        "credentials", sa.Column("issuer_type", _ISSUER_TYPE_ENUM, nullable=True)
    )
    op.add_column(
        "credentials",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "credentials",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "credentials",
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "credentials", sa.Column("rejection_reason", sa.Text(), nullable=True)
    )
    op.create_foreign_key(
        "fk_credentials_reviewed_by_users",
        "credentials",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_credentials_verification_status",
        "credentials",
        ["verification_status"],
    )


def downgrade() -> None:
    """Drop verification columns and enums from credentials."""
    bind = op.get_bind()
    op.drop_index("idx_credentials_verification_status", table_name="credentials")
    op.drop_constraint(
        "fk_credentials_reviewed_by_users", "credentials", type_="foreignkey"
    )
    for column in (
        "rejection_reason",
        "reviewed_by",
        "verified_at",
        "submitted_at",
        "issuer_type",
        "reference_number",
        "verification_url",
        "credential_type",
        "verification_status",
    ):
        op.drop_column("credentials", column)
    _ISSUER_TYPE_ENUM.drop(bind, checkfirst=True)
    _STATUS_ENUM.drop(bind, checkfirst=True)
