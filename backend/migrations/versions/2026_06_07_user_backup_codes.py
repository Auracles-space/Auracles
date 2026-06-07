"""Add single-use 2FA backup code storage.

Revision ID: 2026_06_07_0003
Revises: 2026_06_07_0002
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_07_0003"
down_revision: str | Sequence[str] | None = "2026_06_07_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create hashed, single-use backup codes for TOTP recovery."""
    op.create_table(
        "user_backup_codes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "code_hash", name="uq_backup_codes_user_hash"),
    )
    op.create_index(
        "ix_user_backup_codes_user_id_used_at",
        "user_backup_codes",
        ["user_id", "used_at"],
    )


def downgrade() -> None:
    """Remove TOTP backup code storage."""
    op.drop_index(
        "ix_user_backup_codes_user_id_used_at",
        table_name="user_backup_codes",
    )
    op.drop_table("user_backup_codes")
