"""Add virus-scan state to KYC documents.

Supports FR-AUTH-009 (manual KYC document submission). An admin opens these
files during review, so an uploaded identity document must be scanned before it
can be downloaded — the same guarantee Deliverables and workspace attachments
already have.

``awaiting_upload`` is the state between issuing a presigned POST target and the
browser actually uploading. It keeps reserved-but-never-uploaded rows out of the
user's document list and out of the admin review queue.

Revision ID: 2026_09_06_0099
Revises: 2026_09_06_0098
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_09_06_0099"
down_revision: str | Sequence[str] | None = "2026_09_06_0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

kyc_document_scan_status_enum = postgresql.ENUM(
    "awaiting_upload",
    "pending_scan",
    "clean",
    "quarantined",
    name="kyc_document_scan_status_enum",
    create_type=False,
)


def upgrade() -> None:
    """Add virus-scan state to KYC documents."""
    bind = op.get_bind()
    kyc_document_scan_status_enum.create(bind, checkfirst=True)
    op.add_column(
        "kyc_documents",
        sa.Column(
            "scan_status",
            kyc_document_scan_status_enum,
            nullable=False,
            server_default="awaiting_upload",
        ),
    )
    # The admin queue filters on submitted-and-scanned documents, so the review
    # list reads this column on every page load.
    op.create_index(
        "idx_kyc_documents_scan_status",
        "kyc_documents",
        ["scan_status"],
    )


def downgrade() -> None:
    """Remove virus-scan state from KYC documents."""
    bind = op.get_bind()
    op.drop_index("idx_kyc_documents_scan_status", table_name="kyc_documents")
    op.drop_column("kyc_documents", "scan_status")
    kyc_document_scan_status_enum.drop(bind, checkfirst=True)
