"""Add identity_verifications table for Persona IDV.

Supports the identity verification design (2026-06-24): replaces admin-manual
KYC doc review with Persona. Each row maps a Persona inquiry id to a user so
the signed webhook decision can drive users.kyc_status. We store no documents.

Revision ID: 2026_06_24_0034
Revises: 2026_06_23_0033
Create Date: 2026-06-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_24_0034"
down_revision: str | Sequence[str] | None = "2026_06_23_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the identity_verifications table."""
    op.create_table(
        "identity_verifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=20),
            nullable=False,
            server_default="persona",
        ),
        sa.Column("inquiry_id", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="created",
        ),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("inquiry_id", name="uq_identity_verifications_inquiry_id"),
    )
    op.create_index(
        "ix_identity_verifications_user_id_created_at",
        "identity_verifications",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    """Drop the identity_verifications table."""
    op.drop_index(
        "ix_identity_verifications_user_id_created_at",
        table_name="identity_verifications",
    )
    op.drop_table("identity_verifications")
