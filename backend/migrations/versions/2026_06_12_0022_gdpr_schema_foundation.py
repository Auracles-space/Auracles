"""Add GDPR data-rights schema foundation.

Supports Phase 5c Slice 1 by creating data export request, account deletion
request, and consent log tables, plus default platform config rows for consent,
deletion grace, and export expiry.

Revision ID: 2026_06_12_0022
Revises: 2026_06_11_0021
Create Date: 2026-06-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_12_0022"
down_revision: str | Sequence[str] | None = "2026_06_11_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA_EXPORT_STATUS = postgresql.ENUM(
    "pending",
    "processing",
    "ready",
    "failed",
    "expired",
    name="data_export_status_enum",
    create_type=False,
)
ACCOUNT_DELETION_STATUS = postgresql.ENUM(
    "pending",
    "scheduled",
    "blocked",
    "cancelled",
    "completed",
    name="account_deletion_status_enum",
    create_type=False,
)
CONSENT_DOCUMENT = postgresql.ENUM(
    "terms_of_service",
    "privacy_policy",
    name="consent_document_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create GDPR tables, enum types, indexes, and config defaults."""
    bind = op.get_bind()
    DATA_EXPORT_STATUS.create(bind, checkfirst=True)
    ACCOUNT_DELETION_STATUS.create(bind, checkfirst=True)
    CONSENT_DOCUMENT.create(bind, checkfirst=True)

    op.create_table(
        "data_export_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            DATA_EXPORT_STATUS,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("bundle_key", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_data_export_requests_user_status",
        "data_export_requests",
        ["user_id", "status"],
    )
    op.create_index(
        "uq_data_export_requests_one_active",
        "data_export_requests",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )

    op.create_table(
        "account_deletion_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            ACCOUNT_DELETION_STATUS,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "blocked_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_account_deletion_requests_status_scheduled",
        "account_deletion_requests",
        ["status", "scheduled_for"],
    )
    op.create_index(
        "uq_account_deletion_requests_one_active",
        "account_deletion_requests",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'scheduled')"),
    )

    op.create_table(
        "consent_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_type", CONSENT_DOCUMENT, nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.execute(
        """
        CREATE INDEX idx_consent_logs_user_document_accepted
        ON consent_logs (user_id, document_type, accepted_at DESC)
        """
    )

    op.execute(
        """
        INSERT INTO platform_config (key, value)
        VALUES
            ('consent_version_terms_of_service', '1.0'),
            ('consent_version_privacy_policy', '1.0'),
            ('account_deletion_grace_days', '14'),
            ('data_export_expiry_days', '7')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    """Remove GDPR schema foundation objects and config defaults."""
    op.execute(
        """
        DELETE FROM platform_config
        WHERE key IN (
            'consent_version_terms_of_service',
            'consent_version_privacy_policy',
            'account_deletion_grace_days',
            'data_export_expiry_days'
        )
        """
    )
    op.execute(
        "DROP INDEX IF EXISTS idx_consent_logs_user_document_accepted"
    )
    op.drop_table("consent_logs")
    op.drop_index(
        "uq_account_deletion_requests_one_active",
        table_name="account_deletion_requests",
    )
    op.drop_index(
        "idx_account_deletion_requests_status_scheduled",
        table_name="account_deletion_requests",
    )
    op.drop_table("account_deletion_requests")
    op.drop_index(
        "uq_data_export_requests_one_active",
        table_name="data_export_requests",
    )
    op.drop_index(
        "idx_data_export_requests_user_status",
        table_name="data_export_requests",
    )
    op.drop_table("data_export_requests")

    bind = op.get_bind()
    CONSENT_DOCUMENT.drop(bind, checkfirst=True)
    ACCOUNT_DELETION_STATUS.drop(bind, checkfirst=True)
    DATA_EXPORT_STATUS.drop(bind, checkfirst=True)
