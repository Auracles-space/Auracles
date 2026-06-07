"""Create empty baseline for Phase 0 foundation.

Establishes Alembic revision tracking before business tables are introduced
by their owning feature phases.

Revision ID: 2026_06_07_0001
Revises:
Create Date: 2026-06-07
"""

revision: str = "2026_06_07_0001"
down_revision: str | list[str] | None = None
branch_labels: str | list[str] | None = None
depends_on: str | list[str] | None = None


def upgrade() -> None:
    """Apply the empty Phase 0 baseline."""


def downgrade() -> None:
    """Rollback the empty Phase 0 baseline."""
