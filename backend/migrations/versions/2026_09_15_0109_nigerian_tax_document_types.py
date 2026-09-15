"""Add Nigerian tax document types.

Nigerian organizations could only declare US IRS forms (W-9, W-8BEN) or
"other". Nigeria is the pilot market, so the FIRS TIN certificate and the Tax
Clearance Certificate get their own types and admins can tell them apart. The
downgrade folds rows back to ``other``; the enum values stay because Postgres
cannot remove one.

Revision ID: 2026_09_15_0109
Revises: 2026_09_14_0108
Create Date: 2026-09-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_09_15_0109"
down_revision: str | Sequence[str] | None = "2026_09_14_0108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_VALUES = ("firs_tin", "tcc")
TABLES = ("org_attestor_applications", "org_legal_profiles")


def upgrade() -> None:
    """Add the Nigerian tax document enum values."""
    for value in NEW_VALUES:
        op.execute(
            f"ALTER TYPE tax_document_type_enum ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    """Fold Nigerian document rows back to ``other``; the enum values stay."""
    for table in TABLES:
        op.execute(
            f"UPDATE {table} SET tax_document_type = 'other' "
            f"WHERE tax_document_type::text IN ('firs_tin', 'tcc')"
        )
