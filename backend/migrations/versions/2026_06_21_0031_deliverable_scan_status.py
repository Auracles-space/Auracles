"""Add scan_status to deliverables for malware gating.

Deliverable evidence files are uploaded via the workspace presigned session but
were never virus-scanned (the scan task was message-bound). This adds a
``scan_status`` so a ClamAV scan can gate Operator approval until files are
``visible``; existing rows predate scanning and are treated as ``visible``.

Revision ID: 2026_06_21_0031
Revises: 2026_06_21_0030
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_21_0031"
down_revision: str | Sequence[str] | None = "2026_06_21_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the scan-status enum and add the gated column."""
    op.execute(
        "CREATE TYPE deliverable_scan_status_enum AS ENUM "
        "('pending_scan', 'visible', 'quarantined')"
    )
    op.add_column(
        "deliverables",
        sa.Column(
            "scan_status",
            postgresql.ENUM(
                "pending_scan",
                "visible",
                "quarantined",
                name="deliverable_scan_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="pending_scan",
        ),
    )
    # Existing deliverables were accepted before scanning existed; keep visible.
    op.execute("UPDATE deliverables SET scan_status = 'visible'")


def downgrade() -> None:
    """Drop the scan-status column and enum."""
    op.drop_column("deliverables", "scan_status")
    op.execute("DROP TYPE deliverable_scan_status_enum")
