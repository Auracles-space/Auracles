"""Add Framework thumbnail storage key.

Revision ID: 2026_06_07_0006
Revises: 2026_06_07_0005
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_06_07_0006"
down_revision: str | Sequence[str] | None = "2026_06_07_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store generated thumbnail S3 object keys on Framework rows."""
    op.add_column("frameworks", sa.Column("thumbnail_key", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove generated thumbnail S3 object keys from Framework rows."""
    op.drop_column("frameworks", "thumbnail_key")
