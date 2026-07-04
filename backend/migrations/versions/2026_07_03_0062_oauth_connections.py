"""Add oauth_connections table for external file-provider grants.

Supports Framework Artifact Connectors Phase A: per-user Google Drive
connections with Fernet-encrypted tokens, feeding the import copy-in flow.

Revision ID: 2026_07_03_0062
Revises: 2026_07_03_0061
Create Date: 2026-07-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_03_0062"
down_revision: str | None = "2026_07_03_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the oauth_connections table."""
    op.create_table(
        "oauth_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_account_email", sa.String(255), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.String(500), nullable=False),
        sa.Column(
            "status", sa.String(20), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "provider", name="uq_oauth_connections_user_provider"
        ),
    )
    op.create_index("ix_oauth_connections_user_id", "oauth_connections", ["user_id"])


def downgrade() -> None:
    """Drop the oauth_connections table."""
    op.drop_index("ix_oauth_connections_user_id", table_name="oauth_connections")
    op.drop_table("oauth_connections")
