"""attestor_confidentiality_nda.

Revision ID: 2026_06_30_0046
Revises: 2026_06_30_0045
Create Date: 2026-06-30 13:09:47.938843
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_06_30_0046"
down_revision: str | Sequence[str] | None = "2026_06_30_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.add_column(
        "attestor_applications",
        sa.Column(
            "confidentiality_signed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "attestor_profiles",
        sa.Column(
            "confidentiality_signed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Rollback the migration."""
    op.drop_column("attestor_profiles", "confidentiality_signed_at")
    op.drop_column("attestor_applications", "confidentiality_signed_at")
