"""Add scan status to attestation upload sessions.

Revision ID: 2026_06_10_0014
Revises: 2026_06_10_0013
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_10_0014"
down_revision: str | Sequence[str] | None = "2026_06_10_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

attestation_upload_scan_status_enum = postgresql.ENUM(
    "pending_scan",
    "clean",
    "infected",
    "error",
    name="attestation_upload_scan_status_enum",
    create_type=False,
)


def upgrade() -> None:
    """Add virus-scan state to Attestation upload sessions."""
    bind = op.get_bind()
    attestation_upload_scan_status_enum.create(bind, checkfirst=True)
    op.add_column(
        "attestation_upload_sessions",
        sa.Column(
            "scan_status",
            attestation_upload_scan_status_enum,
            nullable=False,
            server_default="pending_scan",
        ),
    )
    op.create_index(
        "idx_attestation_upload_sessions_scan_status",
        "attestation_upload_sessions",
        ["scan_status"],
    )


def downgrade() -> None:
    """Remove virus-scan state from Attestation upload sessions."""
    bind = op.get_bind()
    op.drop_index(
        "idx_attestation_upload_sessions_scan_status",
        table_name="attestation_upload_sessions",
    )
    op.drop_column("attestation_upload_sessions", "scan_status")
    attestation_upload_scan_status_enum.drop(bind, checkfirst=True)
